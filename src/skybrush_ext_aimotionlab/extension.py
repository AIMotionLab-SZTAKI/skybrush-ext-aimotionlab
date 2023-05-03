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
    def __init__(self):
        super().__init__()
        self._active_traj_ID = 2
        self._hover_traj_defined = False
        self._traj = b''
        self._transmission_active = False

    async def takeoff(self, uav: CrazyflieUAV, server_stream: trio.SocketStream):
        await uav.takeoff(altitude=0.5)
        await server_stream.send_all(b'Takeoff command received.')

    async def land(self, uav: CrazyflieUAV, server_stream: trio.SocketStream):
        await uav.land()
        await server_stream.send_all(b'Land command received.')

    async def start_traj(self, uav: CrazyflieUAV, server_stream: trio.SocketStream):
        cf = uav._get_crazyflie() #access to protected member, but IDC
        await cf.high_level_commander.start_trajectory(1, time_scale=1, relative=False, reversed=False)
        await server_stream.send_all(b'Trajectory start command received.')

    async def upload_trajectory(self, uav: CrazyflieUAV, server_stream: trio.SocketStream):
        trajectory_data = None
        # with open('/home/aimotion-i9/Skyc files/trajectory_circle.json') as json_file:
        #     trajectory_data = json.load(json_file)
        with open('/home/aimotion-i9/Skyc files/hover.json') as json_file:
            # upload 'fallback' hover to ID 1. Length should be about 30
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
        # start_addr is longer than the length of the skybrush show memory, so 100
        # will suffice.
        start_addr = 100
        data = encode_trajectory(trajectory, encoding=TrajectoryEncoding.COMPRESSED)
        traj_checksum = await write_with_checksum(trajectory_memory, start_addr, data, only_if_changed=True)
        print(f"length of data+checksum: {traj_checksum + len(data)}")
        await cf.high_level_commander.define_trajectory(1, addr=(start_addr + traj_checksum), type=TrajectoryType.COMPRESSED)
        print("Defined trajectory!")
        self._hover_traj_defined = True
        await server_stream.send_all(b'Trajectory upload command received.')

    async def start_new_traj(self, uav: CrazyflieUAV, server_stream: trio.SocketStream):
        cf = uav._get_crazyflie() #access to protected member, but IDC
        # initiate hover while we switch trajectories
        if self._hover_traj_defined:
            await cf.high_level_commander.start_trajectory(1, time_scale=1, relative=True, reversed=False)
        # read the trajectory file we just received : this will be the new trajectory we traverse
        with open('./trajectory.json', 'wb') as f:
            f.write(self._traj)
            print("Trajectory saved to local json file (should be fixed later, unnecessary).")
            await server_stream.send_all(b'Trajectory saved.')

        try:
            trajectory_memory = await cf.mem.find(MemoryType.TRAJECTORY)
        except ValueError:
            raise RuntimeError("Trajectories are not supported on this drone") from None
        with open('./trajectory.json') as json_file:
            # we shouldn't need this in-between phase of writing to a json file, maybe we should purge this later
            trajectory_data = json.load(json_file)
        trajectory = TrajectorySpecification(trajectory_data)
        start_addr = 200
        data = encode_trajectory(trajectory, encoding=TrajectoryEncoding.COMPRESSED)
        traj_checksum = await write_with_checksum(trajectory_memory, start_addr, data, only_if_changed=True)
        if traj_checksum + len(data) <= 1940:
            upcoming_traj_ID = 5-self._active_traj_ID
            await cf.high_level_commander.define_trajectory(upcoming_traj_ID, addr=(start_addr + traj_checksum), type=TrajectoryType.COMPRESSED)
            print(f"Defined trajectory on ID {upcoming_traj_ID} (currently active ID is {self._active_traj_ID}).")
            await cf.high_level_commander.start_trajectory(upcoming_traj_ID, time_scale=1, relative=True, reversed=False)
            print(f"Started trajectory on ID {upcoming_traj_ID}")
            self._active_traj_ID = upcoming_traj_ID
        else:
            print(f"Trajectory is too long: {traj_checksum + len(data)} bytes")

    async def start_transmission(self, uav: CrazyflieUAV, server_stream: trio.SocketStream):
        self._transmission_active = True
        print("Transmission of trajectory started.")

    _tcp_command_dict: Dict[str, Callable[[Extension, CrazyflieUAV, trio.SocketStream], None]] = {
        "takeoff": takeoff,
        "land": land,
        "upload": upload_trajectory,
        # "start": start_traj, #SHOULDN'T BE USED FOR NOW
        "TRAJECTORY": start_transmission,
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

    async def TCP_Server(self, server_stream: trio.SocketStream):
        print("Connection made to TCP client.")
        try:
            #for now, let's work with only 1 drone
            uav: CrazyflieUAV = self.app.object_registry.find_by_id("06")
            print("UAV 06 found!")
        except KeyError:
            print("UAV by ID 06 is not found in the client registry.")
            return
        try:
            while True:
                try:
                    # this parsing is very sloppy, should be done better:
                    data: bytes = await server_stream.receive_some()
                    if data.startswith(b'TRAJECTORY'):
                        data = data[len(b'TRAJECTORY'):]
                        self._traj = data
                        cmd = "TRAJECTORY"
                    else:
                        cmd = data.decode("utf-8")
                    # print(f"Received data: {data}")
                    #if there wasn't a trajectory being transmitted:
                    if not self._transmission_active:
                        print(f'Received command: {cmd}')
                        if cmd in self._tcp_command_dict:
                            await self._tcp_command_dict[cmd](self, uav, server_stream)
                        else:
                            print(f"Command {data} is not a recognised command.")
                            await server_stream.send_all(data)
                    else:
                        self._traj += data
                        if self._traj.endswith(b'EOF'):
                            self._traj = self._traj[:-len(b'EOF')]
                            self._transmission_active = False
                            await self.start_new_traj(uav, server_stream)
                            print("Transmission of trajectory ended.")

                except Exception as exc:
                    print(f"Server crashed: {exc!r}")



            # async for data in server_stream:
            #     data: bytes
            #     if data.startswith(b'TRAJECTORY'):
            #         cmd = "TRAJECTORY"
            #     else:
            #         cmd = data.decode("utf-8")
            #     print(f"Received command: {cmd}.")
            #     if cmd in self._tcp_command_dict:
            #         await self._tcp_command_dict[cmd](self, uav, server_stream)
            #     else:
            #         print(f"Command {data} is not a recognised command.")
            #         await server_stream.send_all(data)
            # print(f"TCP connection to client closed.")
        except Exception as exc:
            print(f"Server crashed: {exc!r}")



