/**
 * Prints its own arguments, one per line: "<index> <tab> <argument>".
 *
 * This is the reference half of the .bat parser check. cmd.exe reads a
 * preset line, applies its own rules (%% -> %, %VAR% -> value, ^ escapes,
 * line continuations) and only then starts the program. Whatever this helper
 * receives is exactly what winws.exe would receive - so its output is the
 * truth our parser is compared against.
 *
 * Usage (Windows, from a cmd prompt):
 *   node tools\cmd-argv.js --any --arguments here
 *
 * Run tools\cmd-diff.bat to get cmd's version for every tricky case, then
 *   node verify\strategy-check.js --cases
 * to get our version, and compare the two files.
 */
process.stdout.write(
  process.argv
    .slice(2)
    .map((arg, at) => `${at}\t${arg}`)
    .join('\n') + '\n'
)
