# Matterbeam Outreach Generator

A standalone React application for generating and managing Matterbeam LinkedIn outreach workflows via Anthropic's Claude API.

## Prerequisites
- Node.js (v18+ recommended)
- Anthropic API Access (The app communicates directly with Anthropic via browser calls)
- The fetch calls already include `"anthropic-dangerous-direct-browser-access": "true"`, allowing requests direct from the browser. Keep in mind you may need a proxy if Anthropic blocks your origin in the future.

## Getting Started

1. Set your working directory:
   ```bash
   cd path/to/matterbeam-outreach
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Start the dev server:
   ```bash
   npm run dev
   ```

## Key Features
- Paste a LinkedIn profile to generate outreach messages (Comment, DM, Follow-Up).
- View History of generated profiles, edit statuses, and generate follow-up messages based on user replies.
- The state is persistently saved in your browser via `localStorage` (key: `mb_v6`).
