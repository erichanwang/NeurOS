# Bash completions for NeurOS CLI tools
# Source this in your .bashrc: source /etc/neuros-completions.bash

# nn completions
_nn_complete() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local opts="-i -h --help"
  COMPREPLY=($(compgen -W "$opts" -- "$cur"))
}
complete -F _nn_complete nn

# neuros-model completions
_neuros_model_complete() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local prev="${COMP_WORDS[COMP_CWORD-1]}"
  local cmds="list pull remove switch info search benchmark compare"

  if [[ "$prev" == "neuros-model" ]]; then
    COMPREPLY=($(compgen -W "$cmds" -- "$cur"))
  fi
}
complete -F _neuros_model_complete neuros-model

# neuros-snippets completions
_neuros_snippets_complete() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local prev="${COMP_WORDS[COMP_CWORD-1]}"
  local cmds="save list search show delete generate export"

  if [[ "$prev" == "neuros-snippets" ]]; then
    COMPREPLY=($(compgen -W "$cmds" -- "$cur"))
  fi
}
complete -F _neuros_snippets_complete neuros-snippets

# neuros-git completions
_neuros_git_complete() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local prev="${COMP_WORDS[COMP_CWORD-1]}"
  local cmds="commit review pr changelog explain"

  if [[ "$prev" == "neuros-git" ]]; then
    COMPREPLY=($(compgen -W "$cmds" -- "$cur"))
  fi
}
complete -F _neuros_git_complete neuros-git

# neuros-agent completions
_neuros_agent_complete() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local prev="${COMP_WORDS[COMP_CWORD-1]}"
  local cmds="context clipboard windows index search status"

  if [[ "$prev" == "neuros-agent" ]]; then
    COMPREPLY=($(compgen -W "$cmds" -- "$cur"))
  fi
}
complete -F _neuros_agent_complete neuros-agent
