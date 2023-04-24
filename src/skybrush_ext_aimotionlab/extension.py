from trio import sleep
from flockwave.server.app import SkybrushServer
from flockwave.server.ext.base import Extension
from contextlib import ExitStack
from functools import partial
from flockwave.server.ext.motion_capture import MotionCaptureFrame
from trio import sleep_forever
from .handler import AiMotionMocapFrameHandler

__all__ = ("ext_aimotionlab", )


class ext_aimotionlab(Extension):
    """Extension that broadcasts the pose of non-UAV objects to the Crazyflie drones."""
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
            await sleep_forever()

    def _on_motion_capture_frame_received(
            self,
            sender,
            *,
            frame: "MotionCaptureFrame",
            handler: AiMotionMocapFrameHandler,
    ) -> None:
        handler.notify_frame(frame)





