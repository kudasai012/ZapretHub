@echo off
rem --------------------------------------------------------------------
rem Differential check: cmd.exe vs the .bat parser built into Zapret Hub.
rem
rem Every line below is a preset-like command. cmd.exe reads it with all
rem its rules (%% -> %, %VAR% -> value, ^ escapes, ^ at end of line joins
rem the next line, quotes group tokens) and only then starts the helper,
rem which prints the arguments it really received - exactly what
rem winws.exe would get from this line.
rem
rem Run:
rem   cmd-diff.bat > cmd-argv.txt
rem   node verify\strategy-check.js --cases > hub-argv.txt
rem   fc cmd-argv.txt hub-argv.txt
rem
rem The two files must be identical. Our half prints @DIR@ where a real
rem path stands and uses / as the separator, so the paths here are
rem written the same way on purpose.
rem
rem BIN, LISTS, GameFilterTCP and GameFilterUDP are set to the values the
rem parser substitutes by default - run this with the game filter off.
rem ASCII only, no delayed expansion: the same rules as in the presets.
rem --------------------------------------------------------------------
setlocal
set "BIN=@DIR@/bin/"
set "LISTS=@DIR@/lists/"
set "SPACY=@DIR@/my lists/"
set "GameFilterTCP=12"
set "GameFilterUDP=12"

node "%~dp0cmd-argv.js" case=1 --dpi-desync-fake-tls=^! --wf-tcp=80,443
node "%~dp0cmd-argv.js" case=2 --literal=100%% --num=50%%
node "%~dp0cmd-argv.js" case=3 --redirect=a^<b --open=a^(b --close=a^)b
node "%~dp0cmd-argv.js" case=4 --amp=a^&b --pipe=a^|b --gt=a^>b
node "%~dp0cmd-argv.js" case=5 --hostlist="%LISTS%list-general.txt" --plain=%BIN%winws.exe
node "%~dp0cmd-argv.js" case=6 --quoted="%SPACY%list.txt" --bare=%SPACY%list.txt
node "%~dp0cmd-argv.js" case=7 --glue=abc^
def --wf-udp=443
node "%~dp0cmd-argv.js" case=8 --quoted="a^b" --escaped-quote=a^"b
node "%~dp0cmd-argv.js" case=9 --caret=a^^b --space=one^ two
node "%~dp0cmd-argv.js" case=10 --game=%GameFilterTCP% --udp=%GameFilterUDP%
endlocal

rem --------------------------------------------------------------------
rem Deliberate deviations. They are NOT run above, so fc stays clean:
rem a clean diff means a real regression is visible at once.
rem
rem 1. %NOPE%, an unknown variable. cmd: replaced by nothing, so the
rem    argument silently loses its value. We keep it as typed and write
rem    it to the log - an empty argument is harder to find than a visible
rem    one, and a leftover %GameFilterTCP% would have killed winws.
rem
rem 2. ^%VAR^% and a lone ^%. cmd expands percent signs before it even
rem    looks at carets, so in a .bat file a caret cannot protect a
rem    percent: %VAR^% is an unknown name and goes to nothing, an
rem    unpaired % is dropped. We do the opposite on purpose - ^%VAR^%
rem    arrives as %VAR%, so a literal percent survives instead of
rem    disappearing. (At the command prompt, not in a .bat file, cmd
rem    keeps a lone % and echo ^% does print %.)
rem
rem 3. ^ at the end of a line. cmd joins the next line and, as a quirk,
rem    also escapes its first character. We only join: a preset continues
rem    with " --flag", where there is no difference, while eating the
rem    first character would glue an argument to the next line.
rem --------------------------------------------------------------------
