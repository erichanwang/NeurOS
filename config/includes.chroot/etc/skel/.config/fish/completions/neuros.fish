# NeurOS Fish Shell Completions
# Place in: ~/.config/fish/completions/

# nn completions
complete -c nn -s i -d "Interactive chat mode"
complete -c nn -s h -d "Show help"
complete -c nn -l help -d "Show help"

# neuros-model completions
complete -c neuros-model -f
complete -c neuros-model -n "not __fish_seen_subcommand_from list pull remove switch info search benchmark compare" \
    -a "list pull remove switch info search benchmark compare"
complete -c neuros-model -n "__fish_seen_subcommand_from pull" -a "(ollama list 2>/dev/null | awk 'NR>1{print \$1}')"

# neuros-snippets completions
complete -c neuros-snippets -f
complete -c neuros-snippets -n "not __fish_seen_subcommand_from save list search show delete generate export" \
    -a "save list search show delete generate export"

# neuros-git completions
complete -c neuros-git -f
complete -c neuros-git -n "not __fish_seen_subcommand_from commit review pr changelog explain" \
    -a "commit review pr changelog explain"

# neuros-chat completions
complete -c neuros-chat -l port -d "Server port" -a "(seq 1024 65535)"
complete -c neuros-chat -l no-browser -d "Do not open browser"

# neuros-agent completions
complete -c neuros-agent -f
complete -c neuros-agent -n "not __fish_seen_subcommand_from context clipboard windows index search status" \
    -a "context clipboard windows index search status"

# neuros-voice completions
complete -c neuros-voice -s d -l duration -d "Recording duration in seconds"
complete -c neuros-voice -s f -l file -d "Transcribe audio file"
complete -c neuros-voice -s c -l continuous -d "Continuous dictation"
complete -c neuros-voice -s l -l list -d "List audio devices"
complete -c neuros-voice -s n -l no-response -d "Only transcribe"

# neuros-speak completions
complete -c neuros-speak -s f -l file -d "Read text from file"
complete -c neuros-speak -s p -l pipe -d "Read from stdin"
complete -c neuros-speak -s v -l voice -d "Voice name"
complete -c neuros-speak -s s -l speed -d "Speech speed"
complete -c neuros-speak -s e -l engine -a "piper espeak" -d "TTS engine"
complete -c neuros-speak -s l -l list-voices -d "List voices"
