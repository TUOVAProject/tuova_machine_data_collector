# tuova_machine_data_collector

> ## IMPORTANT!
>
> This repository was created as part of the TUOVA Project (see https://tuova.savonia.fi and https://tuovaproject.github.io/). Some of the information presented here might assume familiarity with other repositories created during the course of the project. For more details on those, see the "Additional Information" section at the bottom of this README.
>
> **Everything is provided as-is, use at your own risk.**
>
> TUOVA Project co-funded by the European Union / Etelä-Savon ELY-keskus.
>
> ![Co-funded by the EU](co-fundedbythe-eu.png)

Author: Timo Lassila, RDI specialist at Savonia University of Applied Sciences

AI has been used in the development process.

## General

This repository contains a Python service that collects CNC machine data from an MTConnect agent and stores it in an InfluxDB (v.2) database:

1. Poll the agent's `current` endpoint at a fixed interval (default every 15 seconds)
2. Parse the MTConnect XML into data points (one per data item)
3. Drop values that have not changed since the previous poll ([how](docs/how-it-works.md#sequence-number))
4. Write the remaining values to InfluxDB

[Read more about MTConnect standard](https://mtconnect.mintlify.app/ "An open, royalty-free standard (ANSI/MTC1.4-2018) that defines a semantic vocabulary for manufacturing equipment data.")

How each step works, and the concepts needed to follow it, is explained in [How the collector works](docs/how-it-works.md).

The data is written into two measurements:

| Measurement   | Field           | Content                                                                 |
| ------------- | --------------- | ----------------------------------------------------------------------- |
| `mtc_metrics` | `value` (float) | Numeric values, e.g. spindle speed, loads, overrides, time counters     |
| `mtc_status`  | `state` (text)  | States and conditions, e.g. execution, mode, program, `UNAVAILABLE`     |
| `mtc_status`  | `online` (1/0)  | Whether the agent answered (`name` = `machine_status`), written on change |

Every row has the tags `device`, `component`, `element` and `name`. The tag values are in lower case, except `device`, which keeps the identifier as the agent gives it. Which data item goes to which measurement: [How an item is routed](docs/how-it-works.md#how-an-item-is-routed).

These measurements are the input of the machine data ETL process ([tuova_machine_data_etl](https://github.com/TUOVAProject/tuova_machine_data_etl)), which turns them into machine events.

## Prerequisites

- An MTConnect agent reachable over HTTP from the host running the collector [MTConnect Demo for testing](https://demo.mtconnect.org/current)
- An InfluxDB 2.x database with a bucket and a token that has write access to it
- Docker with Docker Compose (https://docs.docker.com/engine/install "Install for Linux or Windows Subsystem for Linux")
- For the local test environment: a bash shell

## Development on Linux OS

The repository includes a local test environment for Linux OS that needs no external services. It contains a throwaway InfluxDB 2.7, a simulated MTConnect agent and the collector polling it. The agent (`dev/fake_agent.py`) serves the bundled sample (`MTConnect-sample/`, a `current` snapshot of a real machine with identifiers anonymised) and gives a few fields a new random value on every poll, like a running machine.

```bash
dev/test.sh          # unit tests + smoke test
dev/test.sh unit     # unit tests only (no InfluxDB needed)
dev/test.sh smoke    # a few polls of the simulated agent into the test InfluxDB, then checks
dev/test.sh down     # stop the environment and delete its data
```

The source code is mounted into the test container, so code changes are tested without rebuilding the image.

Test InfluxDB UI: http://localhost:8096 (`admin` / `local-test-password`). The port can be changed with `TEST_INFLUX_PORT`. The test values live in `dev/test.env` and are not secrets.

To see what would be written without any database (dry run, prints the first points):

```bash
docker compose -f docker-compose.test.yml run --rm --no-deps mtc_processor python -m scripts.quick_test
```

## Configuration

The configuration is split into two files. Connection details are kept in `.env`, and the YAML file refers to them with `${VAR}` or `${VAR:-default}` placeholders. This way one YAML file serves every environment and contains no secrets.

### Connections: `.env`

Create as per `.env.example`. Not to be committed.

- `MTC_AGENT_URL`: The agent's current endpoint, e.g. `http://agent:5000/current`. If empty, the sample file is read instead (testing only).
- `INFLUX_URL`, `INFLUX_ORG`, `INFLUX_BUCKET`, `INFLUX_TOKEN`: Your InfluxDB details. **If `INFLUX_TOKEN` is empty, nothing is written** and the collector only prints the points (dry run).
- `POLL_INTERVAL`: Seconds between polls
- `RUN_ONCE`: `1` = poll once and exit (quick check of a new setup)
- `PROCESSOR_LOG_LEVEL`, `PROCESSOR_LOG_MAX_MB`, `PROCESSOR_LOG_BACKUPS`: Level and rotation of the log file `logs/processor.log`

### Settings: `config/mtc_config.yaml`

Create as per `config/mtc_config.example.yaml`. The file is read when the collector starts, so changes need a restart (`docker compose restart`).

- `device_name`, `device_uuid`: Machine identity for the `machine_status` rows
- `ingest`: Agent URL, request timeout and the sample file
- `influx`: Connection details (placeholders) and `enabled`. `enabled: false` = dry run. `buffer_max_rows`: rows kept while InfluxDB cannot be reached ([how](docs/how-it-works.md#the-service-over-time)).
- `dedupe`: Deduplication on/off (`enabled`)
- `mapping`: Which data items are numeric metrics (`numeric_elements`) and which are states (`status_elements`)

At least the following should be checked before the first run:

- `device_uuid`: Should be the same as the `uuid` of the `DeviceStream` in the agent's XML. The other rows get their `device` tag from the XML, so a mismatch splits one machine into two devices.
- `mapping`: Items are matched by their `name` attribute (case does not matter). The names vary between machines and agents. The agent's `probe` endpoint (e.g. `http://agent:5000/probe`) lists all of them. How the lists decide where an item goes: [How an item is routed](docs/how-it-works.md#how-an-item-is-routed).

## Deployment

1. Copy the repository to the host machine
2. Create `.env` as per the [Configuration](#configuration) section above
3. Create `config/mtc_config.yaml` and check the device identity and mapping
4. Build and start:

```bash
docker compose up -d --build
```

5. Check that it works:

```bash
docker compose logs mtc_processor      # start-up line should show token_set=yes
tail -f logs/processor.log             # detailed log of every processed point
```

In production `MTC_AGENT_URL` must be set. The sample file is not included in the production container.

Set `RUN_ONCE=1` in `.env` for the first start. The collector then polls once, logs every point it received and exits. Remove the setting and start again when the data looks right.

## Code structure

The modules in the order the data flows through them, and how to add new processing or storage targets: [From concepts to code](docs/how-it-works.md#from-concepts-to-code).

## Notes

- SSL certificate verification towards InfluxDB is disabled in `storage/influx.py`.
- At log level `INFO` every processed point is logged. Use `WARNING` in production if the log rotates too fast.
- Structure of MTConnect data differs from source to source. Please checks the results thoroughly!


See [MIT LICENSE](LICENSE)

## Additional Information

### The TUOVA Project

- https://tuova.savonia.fi
- https://tuovaproject.github.io/

### The data model ("Tuotantotiedon tietomalli")

- https://github.com/TUOVAProject/tuotantotiedon-tietomalli
- https://tuovaproject.github.io/tuotantotiedon-tietomalli/

### On-premises server environment

- https://github.com/TUOVAProject/tuova_on_prem_server

### Sensor data collection system

- https://github.com/TUOVAProject/tuova-iot

### Energy analyzer data collection system

- https://github.com/TUOVAProject/tuova_energymeter

### Sensor data ETL process

- https://github.com/TUOVAProject/tuova-sensor-etl

### Sensor data - further processing

- https://github.com/TUOVAProject/tuova_machinedata_processing
