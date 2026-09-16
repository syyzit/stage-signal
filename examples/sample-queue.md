# Sample queue for examples/queue-orchestrator.sh.
#
# Format (intentionally boring):
#   - one stage id per line
#   - blank lines and `#` comments are ignored
#   - leading markdown markers (`- `, `* `, `N. `, `- [ ] `, `- [x] `) and
#     surrounding `**` / backticks are stripped, so this file can live as
#     `.md` and still parse as a plain list.
#
# The orchestrator walks this file top-to-bottom against a single
# stage-signal dir (default: ./.stage-signal). See the header of
# examples/queue-orchestrator.sh for cron / bot calling conventions.

# Overnight demo queue (3 stages, in order):
- [ ] queue-orch-example
- [ ] ci-packaging-check
- [ ] readme-0.1-polish
