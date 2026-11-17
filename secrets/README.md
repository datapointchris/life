# secrets

Encrypted environment files managed by [SOPS](https://github.com/getsops/sops) + [age](https://github.com/FiloSottile/age).

## Prerequisites

- `sops` and `age` installed
- age private key at `~/.config/sops/age/keys.txt`

## Edit production secrets

```bash
sops secrets/secrets.prod.enc.env
```

`secrets.prod.enc.env` is what the app containers read, as `.env`. Its `POSTGRES_USERNAME` is
`life_app`. `secrets.postgres-roles.prod.enc.env` holds `POSTGRES_OWNER_PASSWORD` and
`POSTGRES_SUPERUSER_PASSWORD`, which no container reads: the deploy hands them to the role
convergence and the migration command through `sops exec-env`.

Set a value without printing it or putting it on a command line. `--value-stdin` takes JSON, so a
generated password goes in quoted:

```bash
printf '"%s"' "$(openssl rand -hex 32)" | sops set --value-stdin secrets/secrets.prod.enc.env '["POSTGRES_PASSWORD"]'
```

A changed password reaches its role on the next deploy, which converges both roles.

Opens in `$EDITOR`. SOPS decrypts on open, re-encrypts on save.

## Decrypt to stdout

```bash
sops decrypt secrets/secrets.prod.enc.env
```

## Add a new secret

```bash
sops secrets/secrets.prod.enc.env
# Add NEW_VAR=value, save
```

## Key distribution

Copy `~/.config/sops/age/keys.txt` to any machine that needs to decrypt.
The public key in `.sops.yaml` is safe to share.
