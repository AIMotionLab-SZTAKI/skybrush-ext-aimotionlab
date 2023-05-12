libmotioncapture extension and SZTAKI-aimotionlab extension for Skybrush Server
==============================================================================

This repository contains an experimental extension module to Skybrush Server
that adds support for multiple mocap systems via an abstraction layer offered
by `libmotioncapture` for indoor drone tracking.
This readme contains info about installation and setup. For information about
how the extension works, visit the [Wiki](https://github.com/AIMotionLab-SZTAKI/skybrush-ext-aimotionlab/wiki).

Before we begin
------------

1. You will need to install the driver for the Crazyradio Dongle. Instructions 
   on it can be found here: https://www.bitcraze.io/products/crazyradio-pa/

2. You will need Git and Poetry. You probably already have Git downloaded, but you
   may need to install Poetry. Poetry is a tool that allows you to install Skybrush 
   Server and the extension you are working on in a completely isolated virtual 
   environment. If you are using Windows, you're going to have to add the path where 
   poetry was installed to your Path environmental variable, so pay attention to where 
   it was installed. Before continuing on, in order to make poetry install the virtual 
   environment in your project folder (instead of deep in AppData), run this command: 
   `poetry config virtualenvs.in-project true`.
   
3. You will need a drone with Skybrush compatible firmware. Instructions on achieving
   this can be found here: https://github.com/AIMotionLab-SZTAKI/crazyflie-firmware.
   Do not forget to designate a marker set for the drone in Motive!
   
4. Download skybrush live (AppImage for Linux, exe for Windows):
   https://skybrush.io/modules/live/


If you are using Python 3.10
------------

For the optitrack system to work, we need the libmotioncapture library:
https://github.com/IMRCLab/libmotioncapture
This is available on pypi, however, the version of the library on pypi is
not compatible with Python 3.10, so you're going to need to compile it yourself.
This is currently only achieved easily if you're on Linux. If you're using 
Python 3.10 on windows, theoretically, you could download the compiled wheel from
github artifacts (https://github.com/IMRCLab/libmotioncapture/actions/runs/4399180500),
however, I haven't been able to make it work. For now, if you're using Windows, you
should stick to Python 3.8 or 3.9.

As for Linux & Python 3.10:

1. Check out the libmotioncapture repository: 
   https://github.com/IMRCLab/libmotioncapture
   
2. In the libmotioncapture directory, `git submodule init` & `git submodule` update.
   You may also need to install these packages (and their dependencies):
   `sudo apt install libboost-system-dev libboost-thread-dev libeigen3-dev ninja-build`

3. In the same directory, `python3 -m build`. This creates the necessary
   wheel file in the libmotioncapture/dist directory.
   
4. Check out this repository using git.

5. Open pyproject.toml, and under `[tool.poetry.dependencies]` look for the line
   `motioncapture = { file = "..."}`. Change the path here to wherever your wheel
   for libmotioncapture can be found (for example, libmotioncapture/dist/WHEELNAME.whl).

6. Run `poetry install`; this will create a virtual environment and install
   Skybrush Server with all required dependencies in it, as well as the code
   of the extensions.

7. If any dependencies fail to install at first, you may check their status
   with `poetry show`. If they indeed didn't install, or there is an error with
   the hash, try `poetry update`. If any extensions aren't loaded after the server
   launches, try another `poetry install`.
   
8. Make sure you are connected to the optitrack server **via ethernet**. Wireless connection
   will result in choppy data transfer.

9. Run the server with `poetry run skybrushd -c skybrushd.jsonc`.

10. Start Skybrush Live. When you start Live, the server terminal should tell you that a
   Client is connected. You should be able to see any turned on Drones under UAVs. Before
   doing a takeoff, make sure that the position of the drone is stable. If there is an
   issue with the motion capture system, the drone's position will diverge. If you turned
   on the drone's tracking in motive *after* the server was launched, you need to restart
   the server.

If you are using Python 3.8 or 3.9
------------

1. Check out this repository using git.

2. Open pyproject.toml, and under [tool.poetry.dependencies] look for the line
   `motioncapture = { file = "..."}`. Change this line to the following:
   `motioncapture = "^1.0a1"`
   This will download motioncapture from pypi.

3. Run `poetry install`; this will create a virtual environment and install
   Skybrush Server with all required dependencies in it, as well as the code
   of the extensions.

4. If any dependencies fail to install at first, you may check their status
   with `poetry show`. If they indeed didn't install, or there is an error with
   the hash, try `poetry update`. If any extensions aren't loaded after the server
   launches, try another `poetry install`.
   
5. If you tried to run the server now, you would get error messages telling you
   that you are trying to import a function called 'aclosing', which doesn't exist.
   This function (in the contextlib library) was only implemented in Python 3.10.
   We need to make our own aclosing. In src/skybrush_ext_libmotioncapture/channel.py 
   replace this import line:
   `from contextlib import aclosing`
   with the following:
   `from contextlib import asynccontextmanager`.
   And after your imports, implement this function:
   ```python
   @asynccontextmanager
   async def aclosing(thing):
      try:
         yield thing
      finally:
         await thing.aclose()   
   ```
   
6. Make sure you are connected to the optitrack server **via ethernet**. Wireless connection
   will result in choppy data transfer.

7. Run the server with `poetry run skybrushd -c skybrushd.jsonc`.

8. Start Skybrush Live. When you start Live, the server terminal should tell you that a
   Client is connected. You should be able to see any turned on Drones under UAVs. Before
   doing a takeoff, make sure that the position of the drone is stable. If there is an
   issue with the motion capture system, the drone's position will diverge. If you turned
   on the drone's tracking in motive *after* the server was launched, you need to restart
   the server.
