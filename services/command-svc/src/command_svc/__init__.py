"""command-svc: accepts REST commands, validates against contracts, publishes
MQTT setpoints. Closes the command path twin-hello deliberately left open.
It does not read state: a command needing current state is a client-side
composition, not a new coupling."""
