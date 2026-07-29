def canonicalize(cmd: str) -> str:
    """Semantics-preserving canonicalization for shell commands.
    
    Parses a shell command into tokens and rebuilds it with unified quoting.
    Redundant quotes are stripped, but meaningful quotes (spaces, variables,
    escape sequences) are preserved.
    """
    tokens = []
    current_token = []
    state = 'NORMAL'
    i = 0
    n = len(cmd)
    
    while i < n:
        c = cmd[i]
        if state == 'NORMAL':
            if c in ' \t\n':
                if current_token:
                    tokens.append(current_token)
                    current_token = []
            elif c == "'":
                state = 'SINGLE'
                current_token.append(('SINGLE', ''))
            elif c == '"':
                state = 'DOUBLE'
                current_token.append(('DOUBLE', ''))
            elif c == '\\':
                if i + 1 < n:
                    current_token.append(('UNQUOTED', '\\' + cmd[i+1]))
                    i += 1
                else:
                    current_token.append(('UNQUOTED', '\\'))
            else:
                if not current_token or current_token[-1][0] != 'UNQUOTED':
                    current_token.append(('UNQUOTED', c))
                else:
                    current_token[-1] = ('UNQUOTED', current_token[-1][1] + c)
        elif state == 'SINGLE':
            if c == "'":
                state = 'NORMAL'
            else:
                current_token[-1] = ('SINGLE', current_token[-1][1] + c)
        elif state == 'DOUBLE':
            if c == '"':
                state = 'NORMAL'
            elif c == '\\':
                if i + 1 < n and cmd[i+1] in '"\\$`\n':
                    current_token[-1] = ('DOUBLE', current_token[-1][1] + '\\' + cmd[i+1])
                    i += 1
                else:
                    current_token[-1] = ('DOUBLE', current_token[-1][1] + '\\')
            else:
                current_token[-1] = ('DOUBLE', current_token[-1][1] + c)
        i += 1
        
    if current_token:
        tokens.append(current_token)
        
    rebuilt_tokens = []
    # Any char not in this set forces quotes
    safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.,:/@%+")
    
    for token_parts in tokens:
        needs_quotes = False
        has_specials = False
        full_text = ""
        
        for qtype, text in token_parts:
            # Strip backslashes inside DOUBLE for the raw text check? No, keep it as is.
            if qtype == 'UNQUOTED':
                for ch in text:
                    if ch not in safe_chars:
                        needs_quotes = True
                    if ch in '$`\\':
                        has_specials = True
            elif qtype in ('SINGLE', 'DOUBLE'):
                for ch in text:
                    if ch not in safe_chars:
                        needs_quotes = True
                    if ch in '$`\\':
                        has_specials = True
            
            full_text += text
            
        if not full_text and not token_parts:
            continue
        elif not full_text:
            rebuilt_tokens.append('""')
            continue
            
        if not needs_quotes and not has_specials:
            rebuilt_tokens.append(full_text)
        else:
            if has_specials:
                res = ""
                for qtype, text in token_parts:
                    if qtype == 'SINGLE':
                        res += f"'{text}'"
                    elif qtype == 'DOUBLE':
                        res += f'"{text}"'
                    else:
                        res += text
                rebuilt_tokens.append(res)
            else:
                res = ""
                for qtype, text in token_parts:
                    if qtype == 'UNQUOTED' and text.startswith('\\'):
                        # If it was an escape sequence but we are unifying into double quotes,
                        # double quotes don't escape most things. Best to keep specials logic safe!
                        pass
                    res += text
                rebuilt_tokens.append(f'"{res}"')
                
    return " ".join(rebuilt_tokens)
