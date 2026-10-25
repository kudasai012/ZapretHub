Zapret Hub - run without commands
==================================

This folder is here so you can try the program without typing anything.


START
----
Double-click   run.bat

That is all. The file:

  1. checks that Node.js is installed;
  2. runs "npm install" if the node_modules folder is missing;
  3. runs "npm run build" if the app was never built;
  4. opens the app window.

The first run takes a few minutes: packages download and the app is built.
Every run after that starts in a few seconds.

The black window that run.bat opens stays open while the app runs.
Closing that window closes the app. Do not close it by accident.


WHAT YOU NEED FIRST
-------------------
Node.js 20 LTS - https://nodejs.org/
Without it run.bat says so and stops. Nothing else is needed: Git, Python
and C++ build tools are not required.


IF THE APP DOES NOT START
-------------------------
Double-click   stop.bat        (kills a stuck copy), then run.bat again.

To see the full error instead of a short message, open a terminal in the
project folder and run:

    npm install
    npm run dev


WHERE THE APP KEEPS ITS DATA
----------------------------
Running from the source folder, everything stays beside it:

    components\   downloaded zapret-discord-youtube and tg-ws-proxy
    data\         config.json, components.json, logs

An installed app keeps the program in its own folder and moves what it
downloads and remembers out of the way, to

    %LOCALAPPDATA%\ZapretHub\components\
    %LOCALAPPDATA%\ZapretHub\data\

so that updating the app cannot take the components and the settings with it.
On the first start after an update the old folders are moved there by
themselves. Deleting the app removes them too.

Deleting the data folder resets settings and versions.


PACKAGING INTO AN INSTALLER
---------------------------
Double-click   build-exe.bat   in the project root.
The installer lands in the release\ folder.
