import { defineSetupPluginEntry } from "openclaw/plugin-sdk/channel-core";
import { attpPlugin } from "./src/channel.js";

// Lightweight read-only entry used during onboarding/status. Must NOT spawn the
// python child or open sockets.
export default defineSetupPluginEntry(attpPlugin);
