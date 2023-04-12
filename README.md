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

Anatomy of an extension
-----------------------

A Skybrush extension is usually a class derived from the `Extension` base
class, with an asynchronous `run()` method that gets invoked by the server
when the extension is loaded. The function receives three parameters:

- `app`, which is the global Skybrush Server app object of type
  `flockwave.server.app.SkybrushServer`.

- `configuration`, which is a dictionary holding the keys and values specified
  in the configuration of the extension in `sktybrushd.jsonc`

- `logger`, which is a standard Python logger object (from the `logging` module)
  that you can use from your extension to print into the server logs.

The base class also provides additional _synchronous_ hook functions that you
may use, but all of these are optional:

- `configure()` is invoked _before_ the extension is loaded and receives the
  configuration object only. You may use this to pre-process the configuration
  object and set instance variables based on it so you don't need to pollute
  `run()` with configuration-related things.

- `teardown()` is invoked when the extension is unloaded by the user, after the
   task corresponding to `run()` was already cancelled.

- `spinup()` is invoked when the first client connects to the server; you can
  use this to implement extensions that perform certain functions only when
  there are connected clients.

- `spindown()` is invoked when the last client disconnects from the server.

The `run()` method of the extension is a single asynchronous task that runs in
the top-level task group of the server, in a protected `try..catch` block to
ensure that exceptions raised from the extension do not crash the entire server.
However, typically you will want to run multiple asynchronous tasks from an
extension. You can enter the `use_nursery()` context manager from the main
task of the extension to open a Trio _nursery_ (i.e. an asynchronous task group),
and then you can call the `run_in_background()` method of the extension class
to spawn additional tasks in this nursery. The nursery will wait for all the
spawned tasks to complete. A short extension that spawns two tasks that will
log to the same common logger is as follows:

```python
from trio import sleep

class MyExtension(Extension):
   async def first_task(self, logger):
      while True:
         logger.info("First task")
         await sleep(2)

   async def second_task(self, logger):
      while True:
         logger.info("Second task")
         await sleep(3)

   async def run(self, app, configuration, logger):
      async with self.use_nursery():
         self.run_in_background(self.first_task, logger)
         self.run_in_background(self.second_task, logger)
```

Extension metadata and dependencies
-----------------------------------

Extension metadata (such as its description, configuration schema and so on)
and the list of other extensions that the extension depends on must be listed
in the `__init__.py` file of the extension in top-level variables named
`description`, `schema`, `dependencies` and so on. Refer to the sample
`__init__.py` file provided in this repository for more information.

Accessing core server components from an extension
--------------------------------------------------

Typically you will need to access other parts of the server from an extension
in order to do something useful. You should explore the API offered by the
`app` object passed to the `run()` method of the extension to see what is
available to you; the most frequently used properties and methods of the
`app` object are as follows:

- `app.client_registry` allows you to access the clients connected to the
  server. This property is a _registry_ (derived from the
  `flockwave.server.registries.base.RegistryBase`) class that allows lookups
  by IDs with its `find_by_id()` method and listing all registered IDs with
  the `ids` property. You can also iterate over it as if it was a regular
  Python iterable.

- `app.extension_manager` provides a handle to the extension manager of the
  server. Typically you use this property to talk to other extensions using
  their public API. Calling `app.extension_manager.import_api()` with the
  name of another extension returns a Python dictionary mapping public method
  names of that extension to the corresponding functions.

- `app.object_registry` allows you to access all the model objects registered
  in the server; typically you would use this registry to access the UAVs
  known to the server (but there may also be other types of model objects).
  This registry also allows you to list certain types of objects in the
  registry with the `ids_by_type()` method. For instance, to query the IDs of
  all UAVs, call `app.object_registry.ids_by_type()` with the
  `flockwave.server.model.UAV` class as its argument.

- `app.uav_driver_registry` allows you to access all the classes that are
  registered in the server as UAV _drivers_, i.e. objects that know how to talk
  to a certain type of UAV. Each UAV in the system has a `driver` property that
  points to an instance of one of these driver classes.

- `app.find_uav_by_id()` allows you to find a UAV in the object registry of the
  application by its ID. It receives a string ID and returns an object derived
  from the `flockwave.server.model.UAV` class, or `None` if the UAV with the
  given ID is not registered in the app.
