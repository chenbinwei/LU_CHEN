# AI Video Slicing Product Design

Date: 2026-07-09

Status: Draft for review

Owner: LU_CHEN project

## 1. Product Positioning

This product is an AI-assisted video production tool for users who want to operate film commentary, drama recap, or short-drama matrix accounts.

The core promise is not only "cut a long video into a short video". The product should help users turn one source video into multiple publishable commentary-style videos with less writing, editing, voiceover, subtitle, and format work.

Primary value:

- Save production time.
- Help users produce multiple versions from the same material.
- Make it easier for non-professional editors to create film-commentary-style videos.
- Support matrix account testing by varying duration, voice, BGM, subtitle language, audio mode, and aspect ratio.

The initial product should focus on Chinese commentary voiceover. Multilingual voiceover is out of scope for the first version.

## 2. Target Users

The first target users are not mature professional editors. They are users who want to become film commentary or short-drama creators and need a production tool.

Typical user profile:

- Wants to make film commentary or short-drama recap content.
- Has source videos but lacks writing and editing efficiency.
- Wants to test multiple versions for matrix accounts.
- Prefers a product workflow over command-line tools.
- Does not want to configure model API keys in the commercial version.

## 3. MVP Scope

The MVP should be a local single-user product experience with commercial data structures reserved for future SaaS/subscription development.

Included in MVP:

- One source video per project.
- Multiple versions under one project.
- Project-level transcript and user-supplied context.
- Version-level script, target duration, audio settings, subtitle settings, aspect ratio, and final export.
- Full script preview before generating the final video.
- Optional full-script editing by the user.
- Automatic re-segmentation and visual matching after the user edits the script.
- AI voiceover generation.
- Fish Audio voice clone options.
- Optional BGM.
- Adjustable voiceover speed.
- Adjustable voiceover volume.
- Adjustable BGM volume.
- Two audio modes: pure commentary and key original audio.
- Subtitle burn-in plus SRT export.
- Subtitle languages: Chinese, English, and Chinese-English bilingual.
- Aspect ratios: original aspect ratio and vertical 9:16 with blurred background fill.
- Final video duration should closely match the user's target duration.

Not included in MVP:

- User login.
- Payment.
- Subscription enforcement.
- Multi-user project isolation.
- Cloud storage.
- Full cloud rendering.
- Multi-source batch queue.
- Intelligent subject-following vertical crop.
- Multilingual voiceover.
- User-facing timeline editor.
- Manual per-segment visual editing.
- User review of visual matching before generation.

## 4. Product Flow

The first version should use a guided workflow:

1. User uploads one source video.
2. System extracts audio and generates a timestamped transcript.
3. User fills lightweight video context:
   - Work or topic name.
   - Main characters.
   - Brief plot or event summary.
   - Must-mention points.
   - Forbidden or incorrect plot points.
4. User creates a version under the project.
5. User configures version parameters:
   - Target duration.
   - Audio mode.
   - Voice clone.
   - BGM.
   - Voiceover speed.
   - Voiceover volume.
   - BGM volume.
   - Subtitle language.
   - Aspect ratio.
6. System generates a complete, unsegmented script preview.
7. User either accepts the script or edits the full script.
8. System segments the final script automatically.
9. System matches script segments to source transcript timestamps and video ranges.
10. System generates TTS voiceover.
11. System cuts visuals, handles original audio strategy, mixes BGM, burns subtitles, and exports video.
12. User downloads the final video and SRT files.

The user only reviews the script in the MVP. The user does not review segment-to-picture matching in the first version.

## 5. Project And Version Model

The product should separate project-level understanding from version-level generation.

### Project

A project represents one source video.

Project-level data:

- `user_id`: reserved for future account system. In local MVP, use `local_user`.
- `project_id`
- Source video path or asset ID.
- Extracted audio path.
- Transcript with timestamps.
- Source video duration.
- User-provided context fields.
- Optional project-level analysis or summary.
- Created time.
- Updated time.

### Version

A version represents one output plan for the same source video.

Version-level data:

- `version_id`
- `project_id`
- `parent_version_id`: reserved for copied versions.
- `generation_group_id`: reserved for future one-click multi-version generation.
- `variant_goal`: reserved for future automatic variants.
- Target duration.
- Audio mode.
- Voice clone ID.
- BGM ID or path.
- Voiceover speed.
- Voiceover volume.
- BGM volume.
- Subtitle language.
- Aspect ratio.
- Generated script.
- User-edited final script.
- Segmented script.
- Visual matching result.
- TTS audio path.
- Subtitle files.
- Exported video path.
- Job status.

This structure supports the current manual multi-version workflow and leaves space for future automatic multi-version generation.

## 6. Multi-Version Strategy

The MVP should support single-source multi-version production.

First-version behavior:

- User manually creates a new version.
- User can copy an existing version.
- User changes parameters manually.
- Each version can generate its own script and final video.

Reserved future behavior:

- One-click generation of multiple versions.
- Automatic variants by target duration.
- Automatic variants by script angle.
- Automatic variants by voice, BGM, subtitle language, or aspect ratio.
- Batch task group tracking through `generation_group_id`.

## 7. Context Design

`context.json` should not become a complex user-facing prompt editor.

The system should use two layers:

### System Context Layer

Maintained by developers or advanced operators.

It defines:

- Content type.
- Writing rules.
- Allowed and forbidden inference boundaries.
- Script quality constraints.
- How to tell a complete story.
- How to avoid fabricated plot details.
- How to handle character names and relationships.
- How to select key original audio candidates.
- How to structure narration for the selected content branch.

This layer can still use branches, but the branch should represent a content production pattern rather than a simple "style".

Example branches:

- `film_commentary.classic_scene`
- `film_commentary.plot_recap`
- `film_commentary.character_focus`
- `short_drama.recap`

### User Context Layer

Exposed to users as a lightweight form.

Fields:

- Work or topic name.
- Main characters.
- Brief event or plot summary.
- Must-mention points.
- Forbidden or incorrect content.

The user context layer exists because transcript-only understanding is often incomplete. For example, source dialogue may not mention a character's name, but the commentary script still needs that information.

## 8. Script Workflow

The script is a version-level asset.

The first script output should be a complete, unsegmented script preview. The product should not show internal segment matching at this stage.

Script generation requirements:

- The script should tell a coherent story.
- The script should be suitable for spoken film commentary.
- The script should not be a simple subtitle summary.
- The script should use user-provided context when transcript-only information is insufficient.
- The script should avoid obvious typos, mixed-language artifacts, and unrelated objects or terms.
- The script should respect forbidden content supplied by the user.
- The script should be generated for the target duration.

After the user confirms or edits the script:

1. The final full script is segmented automatically.
2. Each segment receives a duration estimate.
3. Each segment is matched to source transcript/video evidence.
4. The TTS timeline is generated from actual voiceover duration.
5. The final video timeline is built around the confirmed script and target duration.

The user edits the story text, not the timeline.

## 9. Duration Rules

The target duration always means final exported video duration.

For example, if the user requests 120 seconds, the final video should be close to 120 seconds. This includes:

- AI voiceover.
- Key original audio segments, if enabled.
- Required pauses or transitions.
- BGM bed.

The system should validate:

- Target duration must be greater than 0.
- Target duration must be shorter than source video duration.
- Duration tolerance must be non-negative.
- Final export duration should be within configured tolerance where possible.

If the generated voiceover is too short or too long, the system should adjust by:

- Regenerating or revising script length where possible.
- Adjusting TTS speed within acceptable limits.
- Rebuilding visual selections to match actual audio duration.

The product should avoid cases where the user asks for 100 seconds but receives a 60-second final video.

## 10. Audio Modes

The product has two audio modes in the MVP.

### Pure Commentary

Behavior:

- Remove original video audio.
- Use AI voiceover as the main audio.
- Optionally mix BGM.
- Burn generated subtitles.

This mode is the most stable and should remain available as the fallback.

### Key Original Audio

Behavior:

- Most of the video is AI commentary.
- The system automatically selects key original audio moments from the source video.
- During original audio moments, AI voiceover pauses.
- BGM can remain underneath but should be lowered.
- The original audio should come from source timestamps only.

Rules:

- Key original audio should occupy about 10%-20% of final video duration.
- Each key original audio segment should usually be 2-8 seconds.
- Original audio should prioritize conflict points, iconic lines, emotional peaks, or turning points.
- If no reliable original audio segment is found, the system should fall back to pure commentary behavior.
- The system should not fabricate original audio or invent source dialogue.

For a 120-second video, key original audio should usually occupy about 12-24 seconds.

## 11. BGM

BGM should be optional.

MVP controls:

- Select BGM.
- Disable BGM.
- Set BGM volume.

BGM mixing requirements:

- BGM should be audible enough to support mood.
- BGM should not overwhelm voiceover.
- BGM should not start with an awkwardly quiet fade-in unless intentionally configured.
- In key original audio mode, BGM should duck under original audio and voiceover as needed.

Future extensions:

- BGM categories.
- Automatic BGM selection based on content branch.
- Different BGM for different scenes.
- Beat-aware cutting is not required for MVP.

## 12. Voice And TTS

The MVP should support Fish Audio cloned voice options.

User-facing controls:

- Select voice clone.
- Set voiceover speed.
- Set voiceover volume.

Technical expectations:

- Voice clone IDs should be stored as reusable voice assets.
- Voice settings should belong to the version.
- TTS duration should be measured after generation.
- The video timeline should be rebuilt using actual TTS duration.

Commercial version behavior:

- Users should not need to provide Fish Audio or other provider API keys.
- The platform should manage model and TTS providers internally.

Local development behavior:

- API keys can remain in local `.env`.
- `.env` must not be committed.
- `.env.example` should document required variables safely.

## 13. Subtitles

The product should generate subtitles from the final voiceover script, not from the original source transcript.

Reason:

- Final subtitles must follow the new AI voiceover timeline.
- Original transcript timestamps are used for visual matching, not for final subtitle timing.

MVP subtitle outputs:

- Burned-in Chinese subtitles.
- Burned-in English subtitles.
- Burned-in Chinese-English bilingual subtitles.
- Chinese SRT export.
- English SRT export.

Source material guidance:

- Users should be encouraged to upload videos without existing burned-in subtitles.
- If the source video already contains subtitles, generated subtitles may visually overlap.
- OCR removal or subtitle area cleanup is out of scope for MVP.

## 14. Aspect Ratio

The MVP should support two export layouts.

### Original Aspect Ratio

Behavior:

- Keep the source video aspect ratio.
- Useful for preview, horizontal platforms, or quality-safe exports.

### Vertical 9:16 With Blurred Background

Behavior:

- Create a 9:16 vertical video.
- Preserve the complete original frame in the center.
- Fill the background with a scaled blurred version of the same frame.
- Place subtitles in a safe vertical-video area.

The MVP should not implement intelligent subject-following crop. That can be a future premium feature.

## 15. Frontend Direction

Recommended frontend stack:

- React
- TypeScript
- Vite

The frontend should focus on a guided creator workflow, not a professional editing timeline.

Main screens:

- Project list.
- New project upload.
- Project detail.
- User context form.
- Version list.
- Version configuration.
- Script preview and full-script editing.
- Generation progress.
- Export/download screen.

The MVP should not expose complex internals such as prompt configuration, segment matching, or timeline editing.

## 16. Backend Direction

Recommended backend stack:

- FastAPI for future product API.
- Existing Python pipeline as the processing core.
- FFmpeg for audio/video processing.
- Faster-Whisper or equivalent for transcription.
- DashScope/Qwen or another LLM provider for script generation and script processing.
- Fish Audio for TTS and voice clone.

The backend should expose project/version/job concepts even in local mode.

Future API shape:

- `POST /projects`
- `GET /projects`
- `GET /projects/{project_id}`
- `POST /projects/{project_id}/versions`
- `POST /versions/{version_id}/script`
- `PUT /versions/{version_id}/script`
- `POST /versions/{version_id}/render`
- `GET /jobs/{job_id}`
- `GET /versions/{version_id}/exports`

These APIs do not need to be implemented immediately, but the pipeline should move toward this boundary.

## 17. Job And Status Model

Rendering should be modeled as jobs.

Common job statuses:

- `pending`
- `running`
- `failed`
- `done`
- `cancelled`

Common job stages:

- `extract_audio`
- `transcribe`
- `generate_script`
- `segment_script`
- `match_visuals`
- `generate_tts`
- `fit_duration`
- `cut_video`
- `mix_audio`
- `burn_subtitles`
- `export`

This makes the product easier to connect to a frontend and easier to debug.

## 18. Commercial Model

The planned commercial model is subscription/usage quota.

Users should only use the product and should not configure their own API keys in the commercial version.

Recommended quota unit:

- Generated final video minutes.

Additional quota dimensions:

- Number of exports.
- Number of voice clones.
- Concurrent generation jobs.
- Storage duration.
- Access to advanced voices, BGM, or future batch features.

Billing and account systems can be added later. However, the data model should reserve:

- `user_id`
- `duration_seconds`
- `job_id`
- `voice_clone_id`
- Export records

## 19. Future Extensions

Potential future features:

- Multi-source batch queue.
- One-click multi-version generation.
- Multi-language voiceover.
- Intelligent vertical crop with subject tracking.
- Segment-level preview.
- Segment-level visual replacement.
- Team workspaces.
- Cloud rendering.
- Platform-specific export presets.
- Automated title, cover, and description generation.
- Publishing integrations.
- Usage analytics by version.

These should not block the MVP.

## 20. Key Risks

### Script Quality

The product depends heavily on script quality. The script must feel like real human commentary, not a mechanical subtitle summary.

Mitigation:

- Keep user context input lightweight but mandatory enough to fill missing story facts.
- Use system context branches for different content production patterns.
- Keep full-script preview and editing before final rendering.

### Visual Matching Quality

If script-to-source matching is weak, the final video will feel disconnected.

Mitigation:

- Match script segments only to source transcript/video evidence.
- Keep segment confidence internally.
- Fall back to safer chronological visual matching when semantic confidence is low.

### Duration Accuracy

If target duration is not respected, the product becomes unreliable for users.

Mitigation:

- Validate requested duration against source duration.
- Measure actual TTS duration.
- Rebuild visual timeline around actual audio duration.
- Enforce final duration tolerance.

### Key Original Audio Risk

Automatic original audio selection may choose weak or confusing moments.

Mitigation:

- Limit original audio ratio to 10%-20%.
- Prefer short original audio segments.
- Require source transcript evidence.
- Fall back to pure commentary when confidence is low.

### Copyright And Platform Risk

Film and drama source videos may involve copyright restrictions.

Mitigation:

- Product design should avoid encouraging infringement.
- Future commercial version may need user responsibility terms, content policy, and takedown handling.

## 21. Acceptance Criteria For MVP

The MVP is successful when:

- A user can create a project from one source video.
- The system can transcribe the source video.
- The user can provide lightweight context.
- The user can create more than one version from the same source video.
- Each version can have its own target duration, audio mode, voice, BGM, subtitle setting, and aspect ratio.
- The system can generate a full script preview.
- The user can edit the full script.
- The system can automatically segment the final script and match it to source video ranges.
- The system can generate voiceover and final video.
- The final video duration is close to the requested target duration.
- The system can export burned-in subtitles and SRT files.
- The same source video can produce at least two meaningfully different versions.

## 22. Self-Review

This design keeps the MVP narrow enough to build:

- It avoids cloud rendering, payment, login, and multi-source batch processing.
- It avoids timeline editing and segment-level visual preview.
- It keeps the user workflow focused on script review and parameter selection.

This design also keeps future product growth possible:

- Project/version/job structure prepares for frontend and SaaS.
- Version model prepares for matrix-account multi-version generation.
- Audio mode design prepares for higher-quality commentary videos.
- Subtitle and aspect ratio settings prepare for short-video platform usage.

Remaining open questions:

- Which context branches should be implemented first?
- What exact tolerance should be used for final duration in production?
- What is the minimum acceptable visual matching confidence?
- How should failed exports refund future commercial quota?
- Should key original audio mode be available in MVP or kept behind an experimental flag first?
