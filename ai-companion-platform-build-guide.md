# AI Companion Platform — Final Project Structure & Build Guide

Stack: **Next.js (web) + Supabase (DB/Auth) + OpenAI (LLM) + Whisper/Deepgram (STT) + ElevenLabs (TTS + consent-gated voice cloning)**

Note on voices: this structure supports custom/cloned voices, but only through the consent-gated flow (Phase 5 below) — original synthetic voices, licensed voice actors with signed releases, or users cloning their own voice. It does not support cloning public figures or scraped audio; that's not something to build in, for the legal reasons covered earlier.

---

## 1. Folder Structure

```
ai-companion-platform/
├── app/                                # Next.js App Router
│   ├── (auth)/
│   │   ├── login/page.tsx
│   │   └── signup/page.tsx
│   ├── (dashboard)/
│   │   ├── chat/[companionId]/page.tsx # main chat UI (text + voice)
│   │   ├── companions/page.tsx         # browse/select companions
│   │   ├── companions/new/page.tsx     # create a custom companion
│   │   └── settings/page.tsx           # account, billing, voice uploads
│   ├── api/
│   │   ├── chat/route.ts               # LLM call, streams response
│   │   ├── stt/route.ts                # speech → text
│   │   ├── tts/route.ts                # text → speech
│   │   ├── voice-clone/route.ts        # consent-gated cloning
│   │   ├── moderation/route.ts         # safety/content filter
│   │   └── webhook/stripe/route.ts     # subscription events
│   ├── layout.tsx
│   └── page.tsx                        # landing/marketing page
│
├── components/
│   ├── chat/
│   │   ├── ChatWindow.tsx
│   │   ├── MessageBubble.tsx
│   │   ├── MicButton.tsx               # record + send audio
│   │   └── VoicePlayer.tsx             # plays TTS audio
│   ├── companions/
│   │   ├── CompanionCard.tsx
│   │   └── CompanionCreator.tsx        # persona + voice picker
│   ├── voice/
│   │   └── ConsentRecorder.tsx         # captures spoken consent clip
│   └── ui/                             # buttons, inputs, modals (shared)
│
├── lib/
│   ├── supabase/
│   │   ├── client.ts                   # browser client
│   │   └── server.ts                   # server client (service role)
│   ├── llm/
│   │   └── openai.ts                   # system prompt + chat completion
│   ├── voice/
│   │   ├── stt.ts                      # Whisper/Deepgram wrapper
│   │   ├── tts.ts                      # ElevenLabs TTS wrapper
│   │   └── clone.ts                    # cloning + consent verification
│   ├── moderation/
│   │   └── contentFilter.ts            # flags self-harm, abuse, etc.
│   └── stripe/
│       └── client.ts
│
├── db/
│   └── schema.sql                      # table definitions (below)
│
├── public/
├── .env.local
├── package.json
├── next.config.js
└── README.md
```

---

## 2. Database Schema (Supabase / Postgres)

```sql
-- users handled by Supabase Auth automatically (auth.users)

create table companions (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references auth.users(id),
  name text not null,
  persona_prompt text not null,      -- system prompt defining personality
  avatar_url text,
  voice_id text,                     -- null = default stock voice
  is_public boolean default false,
  created_at timestamp default now()
);

create table conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id),
  companion_id uuid references companions(id),
  created_at timestamp default now()
);

create table messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid references conversations(id),
  role text check (role in ('user','assistant')),
  content text not null,
  audio_url text,                    -- optional, for voice replies
  created_at timestamp default now()
);

create table voices (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references auth.users(id),
  provider_voice_id text not null,   -- id returned by ElevenLabs etc.
  source_type text check (source_type in ('self','licensed_actor','synthetic_design')),
  consent_recording_url text,        -- proof of consent
  status text check (status in ('pending_review','approved','rejected')) default 'pending_review',
  created_at timestamp default now()
);

create table subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id),
  plan text check (plan in ('free','pro')),
  stripe_customer_id text,
  status text,
  current_period_end timestamp
);
```

---

## 3. Environment Variables (`.env.local`)

```
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
OPENAI_API_KEY=
ELEVENLABS_API_KEY=
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
```

---

## 4. Build Order (step-by-step)

### Phase 1 — Foundation
1. `npx create-next-app@latest ai-companion-platform` → deploy blank app to Vercel immediately.
2. Create Supabase project → run `schema.sql` → connect Supabase Auth.
3. Build login/signup pages using Supabase Auth helpers.

### Phase 2 — Core text chat
4. Build `ChatWindow.tsx` (message list + input).
5. Build `/api/chat/route.ts`: takes message history + `persona_prompt`, calls OpenAI API, streams reply back.
6. Save each message to the `messages` table.
7. Add companion selection (`companions/page.tsx`) pulling from the `companions` table.

### Phase 3 — Companion creation
8. Build `CompanionCreator.tsx`: name, persona description → generates a `persona_prompt` → inserts into `companions`.
9. Add avatar upload (Supabase Storage).

### Phase 4 — Voice input/output
10. Build `MicButton.tsx` → records audio → sends to `/api/stt/route.ts` → returns transcript → feeds into existing chat flow.
11. Build `/api/tts/route.ts`: takes assistant reply text + `voice_id` → calls ElevenLabs → returns audio.
12. Build `VoicePlayer.tsx` to auto-play streamed audio.
13. Add a voice on/off toggle per conversation.

### Phase 5 — Custom voices (consent-gated)
14. Build `ConsentRecorder.tsx`: has the voice owner record a specific spoken consent statement live (not a file upload).
15. Build `/api/voice-clone/route.ts`: sends sample + consent recording to ElevenLabs cloning API → stores `provider_voice_id` in `voices` table with `status = pending_review`.
16. Add a manual/admin review step before a voice flips to `approved` and becomes selectable in `CompanionCreator.tsx`.

### Phase 6 — Safety & moderation
17. Build `contentFilter.ts`: runs on both user input and AI output, flags self-harm/abuse content, routes to appropriate response instead of staying in-persona.
18. Add rate limiting on chat and voice endpoints.
19. Write Terms of Service + Privacy Policy (template service or lawyer review).
20. Add age gating if content leans intimate/romantic.

### Phase 7 — Monetization
21. Integrate Stripe: free tier (limited messages/day, no voice) vs. pro tier (unlimited + voice + custom voices).
22. Build `/api/webhook/stripe/route.ts` to sync subscription status into the `subscriptions` table.
23. Gate voice features behind `subscriptions.plan = 'pro'`.

### Phase 8 — Launch
24. Private beta (10–50 users) → monitor for unsafe outputs and unexpected costs.
25. Track cost-per-conversation (LLM tokens + STT minutes + TTS characters) against pricing.
26. Public launch, then iterate.
