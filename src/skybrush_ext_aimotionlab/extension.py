import trio
from trio import sleep
from flockwave.server.app import SkybrushServer
from flockwave.server.ext.base import Extension
from flockwave.server.ext.crazyflie.driver import CrazyflieUAV
from flockwave.server.ext.crazyflie.trajectory import encode_trajectory, TrajectoryEncoding
from aiocflib.crazyflie.high_level_commander import TrajectoryType
from contextlib import ExitStack
from functools import partial
from flockwave.server.ext.motion_capture import MotionCaptureFrame
from trio import sleep_forever
from .handler import AiMotionMocapFrameHandler
from typing import Dict, Callable
from flockwave.server.show.trajectory import TrajectorySpecification
from aiocflib.crazyflie.mem import write_with_checksum
from aiocflib.crtp.crtpstack import MemoryType
import json

__all__ = ("ext_aimotionlab", )

TCP_PORT = 6000


class ext_aimotionlab(Extension):
    """Extension that broadcasts the pose of non-UAV objects to the Crazyflie drones."""
    # def __init__(self):
    #     super().__init__()
    async def takeoff(self, uav: CrazyflieUAV):
        await uav.takeoff(altitude=0.8)

    async def land(self, uav: CrazyflieUAV):
        await uav.land()

    async def upload_trajectory(self, uav: CrazyflieUAV):
        trajectory_data = None
        with open('/home/aimotion-i9/Skyc files/trajectory_circle.json') as json_file:
            trajectory_data = json.load(json_file)

        cf = uav._get_crazyflie() #access to protected member, but IDC
        try:
            trajectory_memory = await cf.mem.find(MemoryType.TRAJECTORY)
        except ValueError:
            raise RuntimeError("Trajectories are not supported on this drone") from None
        trajectory = TrajectorySpecification(trajectory_data)
        # In the future, we will have separate spaces in the memory for the skybrush
        # show memory and our own. For now, we are just testing, so we will be using
        # a dummy hover skybrush show trajectory, with length 55. Just make sure
        # start_addr is longer than the length of the skybrush show memory, so 200
        # will suffice.
        start_addr = 200
        data = encode_trajectory(trajectory, encoding=TrajectoryEncoding.COMPRESSED)
        traj_checksum = await write_with_checksum(trajectory_memory, start_addr, data, only_if_changed=True)
        print(f"length of data+checksum: {traj_checksum + len(data)}")
        await cf.high_level_commander.define_trajectory(1, addr=(start_addr + traj_checksum), type=TrajectoryType.COMPRESSED)
        print("Defined trajectory!")

    async def start_trajectory(self, uav: CrazyflieUAV):
        cf = uav._get_crazyflie() #access to protected member, but IDC
        await cf.high_level_commander.start_trajectory(1, time_scale=1, relative=False, reversed=False)

    _tcp_command_dict: Dict[str, Callable[[CrazyflieUAV], None]] = {
        "takeoff": takeoff,
        "land": land,
        "upload": upload_trajectory,
        "start": start_trajectory,
    }
    async def run(self, app: "SkybrushServer", configuration, logger):
        """This function is called when the extension was loaded.

        The signature of this function is flexible; you may use zero, one, two
        or three positional arguments after ``self``. The extension manager
        will detect the number of positional arguments and pass only the ones
        that you expect.

        Parameters:
            app: the Skybrush server application that the extension belongs to.
                Also available as ``self.app``.
            configuration: the configuration object. Also available in the
                ``configure()`` method.
            logger: Python logger object that the extension may use. Also
                available as ``self.log``.
        """
        port = configuration.get("port")
        channel = configuration.get("channel")
        assert self.app is not None
        signals = self.app.import_api("signals")
        broadcast = self.app.import_api("crazyflie").broadcast

        self.log.info("The new extension is now running.")
        await sleep(0.5)
        self.log.warning(configuration.get("configWord"))
        await sleep(0.5)
        self.log.info("One second has passed.")

        with ExitStack() as stack:

            # create a dedicated mocap frame handler
            frame_handler = AiMotionMocapFrameHandler(broadcast, port, channel)
            # subscribe to the motion capture frame signal
            stack.enter_context(
                signals.use(
                    {
                        "motion_capture:frame": partial(
                            self._on_motion_capture_frame_received,
                            handler=frame_handler,
                        )
                    }
                )
            )
            # await sleep_forever()
            await trio.serve_tcp(self.TCP_Server, TCP_PORT)
    def _on_motion_capture_frame_received(
            self,
            sender,
            *,
            frame: "MotionCaptureFrame",
            handler: AiMotionMocapFrameHandler,
    ) -> None:
        handler.notify_frame(frame)

    async def TCP_Server(self, server_stream):
        print("Connection made to TCP client.")
        try:
            #for now, let's work with only 1 drone
            uav: CrazyflieUAV = self.app.object_registry.find_by_id("06")
            print("UAV 06 found!")
        except KeyError:
            print("UAV by ID 06 is not found in the client registry.")
            return
        try:
            async for data in server_stream:
                data_str = data.decode("utf-8")
                print(f"Received data: {data_str}")
                if data_str in self._tcp_command_dict:
                    await self._tcp_command_dict[data_str](self, uav)
                await server_stream.send_all(data)
            print(f"TCP connection to client closed.")
        except Exception as exc:
            print(f"Server crashed: {exc!r}")



