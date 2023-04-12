libmotioncapture extension and SZTAKI-aimotionlab extension for Skybrush Server
==============================================================================

This repository contains an experimental extension module to Skybrush Server
that adds support for multiple mocap systems via an abstraction layer offered
by `libmotioncapture` for indoor drone tracking.

Installation
------------

1. Check out the libmotioncapture repository: 
   https://github.com/IMRCLab/libmotioncapture

2. Compile libmotioncapture, you should get a wheel file. If you already have
   a working wheel of the motioncapture library, you may skip these two steps.

3. Check out this repository using git.

4. Install [`poetry`](https://python-poetry.org) if you haven't done so yet;
   `poetry` is a tool that allows you to install Skybrush Server and the
   extension you are working on in a completely isolated virtual environment.

5. Run `poetry install`; this will create a virtual environment and install
   Skybrush Server with all required dependencies in it, as well as the code
   of the extensions.

4. If any dependencies fail to install at first, you may check their status
   with `poetry show`. If they indeed didn't install, try `poetry update`.

6. Run the server with `poetry run skybrushd -c skybrushd.jsonc`.
