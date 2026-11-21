# Mech Royale — Survivor v4

**v4 is based on the v2 agent that scored 2.10 in practice, NOT on the unsuccessful v3.**
The only policy change is a correction of the sign of projectile lateral evasion.
It leaves aiming, target selection, healing policy, resource collection, upgrades, and boost logic untouched.

## Tests (without Docker)

From this folder (with the official kit extracted in `../mechfight-kit`):

```sh
python3 verify_v4.py --kit ../mechfight-kit
python3 ../mechfight-kit/check/check.py -- python3 -u example_bot.py
```

## Docker and official conformance

```sh
docker build -t mech-survivor:v4 .
cd ../mechfight-kit
python3 check/check.py --map-dir /arena -- \
  docker run --rm -i --network none --cpus 1 --memory 512m \
  --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 \
  -v "$PWD/arena:/arena:ro" mech-survivor:v4
```

**Important:** Both checks are static/replay checks. This package does not contain a true match simulator. It cannot predict placement or prove v4 improves on v2.
