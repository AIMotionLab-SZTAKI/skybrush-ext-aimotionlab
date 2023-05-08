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
from typing import Dict, Callable, Union, Tuple, Any
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
        self._stream_data = b''
        self._traj = b''
        self._transmission_active = False
        self._load_from_file = False
        self._memory_partitions = None

    def get_traj_type(self, traj_type: bytes) -> Tuple[bool, bool]:
        traj_type_lower = traj_type.lower()
        if traj_type_lower == b'relative':
            return True, True
        elif traj_type_lower == b'absolute':
            return True, False
        else:
            return False, None



    def parse(self, raw_data: bytes, cmd_dict: Dict[bytes, Tuple[Callable[[Extension, CrazyflieUAV, trio.SocketStream, bytes], None], Tuple[bool, Any], bool]]):
        data = raw_data.strip()
        if not data:
            return None, None
        data = data.split(b'_')
        if data[0] != b'CMDSTART':
            return b'NO_CMDSTART', None
        ID = data[1]
        command = data[2]
        if command not in cmd_dict:
            return b'WRONG_CMD', None
        if cmd_dict[command][1][0]: # This is a boolean signifying whether we expect an argument
            argument = data[3]
        else:
            argument = None
        if cmd_dict[command][2]: # This is a boolean signifying that we are expecting a payload
            self.log.info("Payload expected.")
            # payload = data[4]
            # self._traj = payload
            # #BUG: WHEN THE WHOLE MESSAGE GETS TRANSMITTED IN ONE, WE GET NO EOF AND UPLOAD DOESNT FINISH
        return command, argument

    async def takeoff(self, uav: CrazyflieUAV, server_stream: trio.SocketStream, arg):
        try:
            arg = float(arg)
            if arg < 0.1 or arg > 1.5:
                arg = 0.5
                self.log.warning("Takeoff height was out of allowed bounds, taking off to 0.5m")
            if uav._airborne:
                self.log.warning("Drone is already airborne, takeoff command wasn't dispatched.")
                await server_stream.send_all(b"Drone is already airborne, takeoff command wasn't dispatched.")
            else:
                await uav.takeoff(altitude=arg)
                await server_stream.send_all(b'Takeoff command dispatched to drone.')
                self.log.info("Takeoff command dispatched to drone.")
        except ValueError:
            self.log.warning("Takeoff argument is not a float.")

    async def land(self, uav: CrazyflieUAV, server_stream: trio.SocketStream, arg):
        if uav._airborne:
            await uav.land()
            await server_stream.send_all(b'Land command dispatched to drone.')
            self.log.info("Land command dispatched to drone.")
        else:
            self.log.warning("Drone is already on the ground, land command wasn't dispatched.")
            await server_stream.send_all(b"Drone is already on the ground, land command wasn't dispatched.")

    async def start_traj(self, uav: CrazyflieUAV, server_stream: trio.SocketStream, arg: str):
        cf = uav._get_crazyflie() #access to protected member, but IDC
        await cf.high_level_commander.start_trajectory(1, time_scale=1, relative=False, reversed=False)
        await server_stream.send_all(b'Trajectory start command received.')

    async def upload_hover(self, uav: CrazyflieUAV):
        trajectory_data = None
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
        self.log.info(f"length of data+checksum for hover: {traj_checksum + len(data)}")
        await cf.high_level_commander.define_trajectory(1, addr=(start_addr + traj_checksum), type=TrajectoryType.COMPRESSED)
        self.log.info("Defined fallback hover trajectory!")
        self._hover_traj_defined = True

    async def write_safely(self, traj_id: int, handler, data) -> Tuple[bool, Union[int, None]]:
        start_addr = self._memory_partitions[traj_id]["start"]
        allowed_size = self._memory_partitions[traj_id]["size"]
        checksum_length = await write_with_checksum(handler, start_addr, data, only_if_changed=True)
        self.log.info(f"Checksum length: {checksum_length}, data length: {len(data)}, allowed size: {allowed_size}")
        if len(data)+checksum_length <= allowed_size:
            # self.log.info(f"Wrote trajectory to address {start_addr}")
            return True, start_addr+checksum_length
        else:
            return False, None

    async def handle_new_traj(self, uav: CrazyflieUAV, server_stream: trio.SocketStream, arg: bytes):
        with open('./trajectory.json', 'wb') as f:
            f.write(self._traj)
            self.log.warning("Trajectory saved to local json file for backup.")
            await server_stream.send_all(b'Trajectory saved to local file for backup.')
        is_valid, is_relative = self.get_traj_type(arg)
        if uav.is_running_show and uav._airborne and is_valid:
            cf = uav._get_crazyflie()  # access to protected member
            if not self._hover_traj_defined:
                await self.upload_hover(uav)
            # initiate hover while we switch trajectories
            await cf.high_level_commander.start_trajectory(1, time_scale=1, relative=True, reversed=False)
            try:
                trajectory_memory = await cf.mem.find(MemoryType.TRAJECTORY)
            except ValueError:
                raise RuntimeError("Trajectories are not supported on this drone") from None
            if self._load_from_file:
                with open('./trajectory.json') as json_file:
                    trajectory_data = json.load(json_file)
                self.log.warning("Trajectory read from local json file.")
            else:
                trajectory_data = json.loads(self._traj.decode('utf-8'))
            trajectory = TrajectorySpecification(trajectory_data)
            data = encode_trajectory(trajectory, encoding=TrajectoryEncoding.COMPRESSED)
            upcoming_traj_ID = 5 - self._active_traj_ID
            success, addr = await self.write_safely(upcoming_traj_ID, trajectory_memory, data)
            if success:
                await cf.high_level_commander.define_trajectory(
                    upcoming_traj_ID, addr=addr, type=TrajectoryType.COMPRESSED)
                self.log.info(
                    f"Defined trajectory on ID {upcoming_traj_ID} (currently active ID is {self._active_traj_ID}).")
                await cf.high_level_commander.start_trajectory(upcoming_traj_ID, time_scale=1, relative=is_relative,
                                                               reversed=False)
                self.log.info(f"Started trajectory on ID {upcoming_traj_ID}")
                self._active_traj_ID = upcoming_traj_ID
            else:
                self.log.warning(f"Trajectory is too long.")
        else:
            self.log.warning("Drone is not airborne, running a show. Start the hover show to upload trajectories.")
            await server_stream.send_all(b"Drone is not airborne, running a show. Start the hover show to upload trajectories.")


    async def handle_transmission(self, uav: CrazyflieUAV, server_stream: trio.SocketStream, arg: bytes):
        await server_stream.send_all(b'Transmission of trajectory started.')
        self.log.info("Transmission of trajectory started.")
        # Find where the json file begins
        start_index = self._stream_data.find(b'{')
        # If the command was 'traj', then a json file must follow. If it doesn't (we can't find the beginning {), then
        # the command or the file was corrupted.
        if start_index == -1:
            self.log.warning("Corrupted trajectory file.")
            return
        else:
            self._traj = self._stream_data[start_index:]
        self._transmission_active = True
        while not self._traj.endswith(b'_EOF'):
            self._traj += await server_stream.receive_some()
        self._traj = self._traj[:-len(b'_EOF')]
        self._transmission_active = False
        await self.handle_new_traj(uav, server_stream, arg)
        self._traj = b''
        self.log.info("Transmission of trajectory finished.")
        await server_stream.send_all(b'Transmission of trajectory finished.')

    _tcp_command_dict: Dict[bytes, Tuple[Callable[[Extension, CrazyflieUAV, trio.SocketStream, bytes], None], Tuple[bool, Any], bool]] = {
        b"takeoff": (takeoff, (True, float), False), # The command takeoff takes a float argument and expects no payload
        b"land": (land, (False, None), False), # The command land takes no argument and expects no payload
        b"traj": (handle_transmission, (True, str), True),  # The command traj takes a str argument and expects a payload
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

        self._memory_partitions = configuration.get("memory_partitions")
        port = configuration.get("port")
        channel = configuration.get("channel")
        assert self.app is not None
        signals = self.app.import_api("signals")
        broadcast = self.app.import_api("crazyflie").broadcast

        self.log.info("The new extension is now running.")
        await sleep(1.0)
        self.log.info("One second has passed.")
        with open('./trajectory.json', 'wb') as f:
            f.write(b'')
        self.log.info("Cleared trajectory.json")

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
        self.log.info("Connection made to TCP client.")
        try:
            #for now, let's work with only 1 drone
            uav: CrazyflieUAV = self.app.object_registry.find_by_id("06")
            self.log.info("UAV 06 found!")
        except KeyError:
            self.log.info("UAV by ID 06 is not found in the client registry.")
            return
        while True:
            try:
                # this parsing is very sloppy, should be done better:
                self._stream_data: bytes = await server_stream.receive_some()
                if not self._stream_data:
                    break

                # If we're not in the middle of a trajectory's transition, we can handle commands:
                if not self._transmission_active:
                    cmd, arg = self.parse(self._stream_data, self._tcp_command_dict)
                    if cmd == b'NO_CMDSTART':
                        self.log.info(f"Command is missing standard CMDSTART")
                        await server_stream.send_all(b'Command is missing standard CMDSTART')
                    elif cmd == b'WRONG_CMD':
                        self.log.info(f"Command is not found in server side dictionary")
                        await server_stream.send_all(b'Command is not found in server side dictionary')
                    elif cmd is None:
                        self.log.warning(f"None-type command")
                        await server_stream.send_all(b'None-type command')
                    else:
                        self.log.info(f"Command received: {cmd.decode('utf-8')}")  # Let the user know the command arrived
                        await server_stream.send_all(b'Command received: ' + cmd)  # Let the client know as well
                        await self._tcp_command_dict[cmd][0](self, uav, server_stream, arg)
                else:
                    pass

            except Exception as exc:
                self.log.warning(f"TCP server crashed: {exc!r}")





