# NeurOS Zsh Configuration
# ~/.zshrc for new users (copied from /etc/skel)

# === Path ===
export PATH="$HOME/.local/bin:$PATH"

# === Oh-My-Zsh ===
export ZSH="$HOME/.oh-my-zsh"
ZSH_THEME="agnoster"

# Plugins
plugins=(
  git
  docker
  python
  fzf
)

source $ZSH/oh-my-zsh.sh

# === Aliases ===
alias ll="eza -la --icons"
alias ls="eza --icons"
alias tree="eza -T --icons"
alias cat="bat --style=plain"
alias grep="rg"
alias top="btop"
alias vim="nvim"
alias vi="nvim"

# Git shortcuts
alias gs="git status"
alias ga="git add"
alias gc="git commit -m"
alias gp="git push"
alias gl="git log --oneline --graph"
alias gd="git diff"

# NeurOS
# AI Assistants
alias ai="nn"
alias ask="nn"
alias chat="neuros-chat"
alias nchat="neuros-chat"

# Model Management
alias nm="neuros-model"
alias models="neuros-model list"
alias nmpull="neuros-model pull"
alias nmswitch="neuros-model switch"

# Code Tools
alias snippets="neuros-snippets"
alias ns="neuros-snippets"
alias ngen="neuros-snippets generate"

# Git Assistant
alias ng="neuros-git"
alias ncommit="neuros-git commit"
alias nreview="neuros-git review"
alias npr="neuros-git pr"

# System Agent
alias nagent="neuros-agent"
alias nctx="neuros-agent context"
alias nstatus="neuros-agent status"

# Voice
alias nsay="neuros-speak"
alias nhear="neuros-voice"

# MCP Server
alias nmcp="neuros-mcp"

# === nn shell integration ===
# Ctrl+Space for quick nn access
function nn-widget() {
    BUFFER="nn \"$BUFFER\""
    zle accept-line
}
zle -N nn-widget
bindkey '^@' nn-widget

# === Prompt customization ===
# Add NeurOS indicator to prompt
NEUROS_INDICATOR="🧠"

# === Environment ===
export EDITOR="nvim"
export VISUAL="nvim"
export PAGER="less"

# === History ===
HISTSIZE=50000
SAVEHIST=50000
HISTFILE=~/.zsh_history
setopt SHARE_HISTORY
setopt HIST_IGNORE_DUPS
setopt HIST_IGNORE_SPACE

# === Completions ===
autoload -Uz compinit
compinit
zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-z}={A-Za-z}'

# === Welcome (first run) ===
if [ ! -f "$HOME/.config/neuros/.welcome-shown" ]; then
    echo ""
    echo "  🧠 Welcome to NeurOS!"
    echo "  Type 'nn \"your question\"' to ask the local AI."
    echo "  Type 'nn -i' for interactive mode."
    echo ""
fi
