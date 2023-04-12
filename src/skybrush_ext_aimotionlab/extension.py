from trio import sleep

from flockwave.server.ext.base import Extension

__all__ = ("ext_aimotionlab", )


class ext_aimotionlab(Extension):
    """Template for Skybrush Server extensions."""

    async def run(self, app, configuration, logger):
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
        self.log.info("The new extension is now running.")
        await sleep(0.5)
        self.log.warning(configuration.get("configWord"))
        await sleep(0.5)
        self.log.info("One second has passed.")
