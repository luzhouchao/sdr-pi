# Security policy

This repository must not contain passwords, private keys, access tokens, SSH
agent dumps, or configuration files with embedded credentials.

## Credential handling

- Pass credentials through an interactive prompt, SSH agent, or a local
  untracked environment file.
- CLI password options must default to an empty value.
- Keep local environment files under ignored paths such as `.env` or
  `secrets/`.
- Never commit private keys. Documentation may refer to a key under
  `$HOME/.ssh`, but must not contain key material.

Before each push, run a secret-oriented search in addition to normal tests:

```bash
rg -n -i 'password\s*[:=]|api[_-]?key|token\s*[:=]|secret\s*[:=]|BEGIN .*PRIVATE KEY'
```

Review matches manually because function parameters such as `password` may be
legitimate while literal credential values are not.
