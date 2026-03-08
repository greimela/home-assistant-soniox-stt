# Soniox Speech-to-Text for Home Assistant

Custom Home Assistant speech-to-text integration for [Soniox](https://soniox.com/). It plugs into the normal Assist voice pipeline, so you can select it as the speech-to-text engine for your pipeline and choose how language selection should work.

## Features

- Uses Soniox as a Home Assistant Assist speech-to-text provider
- Works with the normal Assist pipeline
- Supports automatic language handling from the pipeline language
- Supports locking the integration to one specific language
- Configured entirely through the Home Assistant UI

## Requirements

- Home Assistant `2025.12.3` or newer
- A Soniox account
- A Soniox API key

## Installation

### HACS

1. Open HACS in Home Assistant.
2. Add this repository as a custom repository if it is not yet listed in HACS by default.
3. Choose the repository type `Integration`.
4. Install `Soniox Speech-to-Text`.
5. Restart Home Assistant.

### Manual

1. Copy `custom_components/soniox_stt` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

## Setup

1. Open **Settings** → **Devices & Services**.
2. Click **Add Integration**.
3. Search for `Soniox Speech-to-Text`.
4. Enter your Soniox API key.
5. Choose a language mode:
   - `Automatic`: use the active Assist pipeline language
   - A fixed language: always send that language to Soniox
6. Finish the config flow.

Only one Soniox Speech-to-Text entry is supported.

## Use with Assist

After the integration is added:

1. Open **Settings** → **Voice Assistants**.
2. Open the pipeline you want to use.
3. Set **Speech-to-text** to `Soniox Speech-to-Text`.
4. Save the pipeline.

If you use `Automatic` language mode, the Assist pipeline language determines the language Soniox receives. If you choose a fixed language in the integration options, that language is used for every transcription request.

## Changing the Language Later

1. Open **Settings** → **Devices & Services**.
2. Open the `Soniox Speech-to-Text` integration.
3. Click **Configure**.
4. Change the language mode.

## Troubleshooting

- If the integration does not appear in HACS with the right name, refresh HACS metadata and reload the page.
- If setup fails immediately, verify that your Soniox API key is valid.
- If Assist cannot use the provider, confirm that your pipeline has `Soniox Speech-to-Text` selected as its speech-to-text engine.

## Development Status

This repository is currently focused on the Assist STT integration only. The original template boilerplate has been removed in favor of a dedicated Soniox implementation.
