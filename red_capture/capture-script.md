# Commands to run while capturing

Run each as a bot owner in a test-server channel (prefix shown as `[p]`). Press the menu buttons
where noted. Wait for each reply before the next.

1. `[p]help` — then press **next** once if there are several pages
2. `[p]help Core` — the cog page
3. `[p]help set` — a group (its subcommand list)
4. `[p]help ping` — a single command
5. `[p]info`
6. `[p]set showsettings`
7. `[p]permissions explain`
8. `[p]permissions canrun <a test user> ping`
9. `[p]mydata whatdata`
10. Anything that makes a multi-page menu, e.g. `[p]servers` in a bot that is in many servers, or `[p]help` with
    menus on; press forward, back, and the close/stop button.
11. Optional, a modlog case post: if the test bot has a command that creates a case (a ban, a warn), set a
    modlog channel with `[p]modlogset modlog #channel` and run it. The post is recorded because the
    command sends it. Skip this if no such command is loaded; case rendering is already checked against
    Red's own code.
