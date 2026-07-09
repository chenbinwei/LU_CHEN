(() => {
  "use strict";

  const state = {
    projects: [],
    versions: [],
    jobs: [],
    selectedProject: null,
    selectedVersion: null,
    activeJob: null,
    pollTimer: null,
  };

  const $ = (id) => document.getElementById(id);

  async function requestJson(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });
    const text = await response.text();
    const payload = text ? JSON.parse(text) : null;
    if (!response.ok) {
      const detail = payload && payload.detail ? payload.detail : response.statusText;
      throw new Error(detail);
    }
    return payload;
  }

  function showMessage(message) {
    const toast = $("statusMessage");
    toast.textContent = message;
    toast.classList.add("is-visible");
    window.setTimeout(() => toast.classList.remove("is-visible"), 2600);
  }

  function numberValue(id) {
    const value = $(id).value.trim();
    return value ? Number(value) : null;
  }

  function splitLines(value) {
    return value
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
  }

  function listToText(value) {
    return Array.isArray(value) ? value.join("\n") : "";
  }

  function parseCharacters(value) {
    return splitLines(value).map((line) => {
      const parts = line.split(/[:：]/);
      if (parts.length >= 2) {
        return {
          name: parts.shift().trim(),
          role: parts.join("：").trim(),
        };
      }
      return { name: line };
    });
  }

  function charactersToText(value) {
    if (!Array.isArray(value)) {
      return "";
    }
    return value
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        const name = item.name || "";
        const role = item.role || item.description || "";
        return role ? `${name}：${role}` : name;
      })
      .filter(Boolean)
      .join("\n");
  }

  function setActionState() {
    const hasProject = Boolean(state.selectedProject);
    const hasVersion = Boolean(state.selectedVersion);
    $("saveContextButton").disabled = !hasProject;
    $("createVersionButton").disabled = !hasProject;
    $("startRenderButton").disabled = !hasProject || !hasVersion;
  }

  function projectTitle(project) {
    const title = project.context_packet && project.context_packet.title;
    return title || project.source_video_path || project.project_id;
  }

  function renderProjects() {
    const list = $("projectList");
    list.innerHTML = "";
    state.projects.forEach((project) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "item-button";
      if (state.selectedProject && state.selectedProject.project_id === project.project_id) {
        button.classList.add("is-active");
      }
      button.innerHTML = `
        <span class="item-title">${projectTitle(project)}</span>
        <span class="item-meta">${project.project_id}</span>
      `;
      button.addEventListener("click", () => selectProject(project.project_id));
      list.appendChild(button);
    });
  }

  function renderVersions() {
    const list = $("versionList");
    list.innerHTML = "";
    state.versions.forEach((version) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "item-button";
      if (state.selectedVersion && state.selectedVersion.version_id === version.version_id) {
        button.classList.add("is-active");
      }
      const settings = version.settings;
      button.innerHTML = `
        <span class="item-title">${settings.target_duration_seconds}s · ${settings.audio_mode}</span>
        <span class="item-meta">${version.version_id}</span>
      `;
      button.addEventListener("click", () => {
        state.selectedVersion = version;
        renderVersions();
        setActionState();
      });
      list.appendChild(button);
    });
  }

  function renderJobs() {
    const list = $("jobList");
    list.innerHTML = "";
    state.jobs.forEach((job) => {
      const row = document.createElement("div");
      row.className = "job-row";
      row.dataset.status = job.status;
      row.innerHTML = `
        <span class="item-title">${job.status} · ${job.current_stage}</span>
        <span class="item-meta">${job.job_id}</span>
        <span class="item-meta">${job.error_message || JSON.stringify(job.export_paths || {})}</span>
      `;
      list.appendChild(row);
    });
  }

  function fillContextForm(project) {
    const packet = project.context_packet || {};
    $("contextTitle").value = packet.title || "";
    $("sourceType").value = packet.source_type || "";
    $("contextCharacters").value = charactersToText(packet.characters);
    $("correctSynopsis").value = packet.correct_synopsis || "";
    $("storyFocus").value = listToText(packet.story_focus);
    $("externalKnowledge").value = listToText(packet.allowed_external_knowledge);
    $("forbiddenTerms").value = listToText(packet.forbidden_terms);
    $("forbiddenStoryFacts").value = listToText(packet.forbidden_story_facts);
    $("mustNotInclude").value = listToText(packet.must_not_include);
    $("ttsTerms").value = listToText(packet.tts_unfriendly_terms);
  }

  function buildContextPacket() {
    const existing = state.selectedProject && state.selectedProject.context_packet ? state.selectedProject.context_packet : {};
    return {
      ...existing,
      title: $("contextTitle").value.trim(),
      source_type: $("sourceType").value.trim(),
      characters: parseCharacters($("contextCharacters").value),
      correct_synopsis: $("correctSynopsis").value.trim(),
      story_focus: splitLines($("storyFocus").value),
      allowed_external_knowledge: splitLines($("externalKnowledge").value),
      forbidden_terms: splitLines($("forbiddenTerms").value),
      forbidden_story_facts: splitLines($("forbiddenStoryFacts").value),
      must_not_include: splitLines($("mustNotInclude").value),
      tts_unfriendly_terms: splitLines($("ttsTerms").value),
    };
  }

  async function loadProjects() {
    state.projects = await requestJson("/api/projects");
    renderProjects();
  }

  async function loadVersions(projectId) {
    state.versions = await requestJson(`/api/projects/${projectId}/versions`);
    state.selectedVersion = state.versions[0] || null;
    renderVersions();
  }

  async function loadJobs(projectId) {
    state.jobs = await requestJson(`/api/projects/${projectId}/jobs`);
    renderJobs();
  }

  async function selectProject(projectId) {
    state.selectedProject = await requestJson(`/api/projects/${projectId}`);
    fillContextForm(state.selectedProject);
    await loadVersions(projectId);
    await loadJobs(projectId);
    renderProjects();
    setActionState();
  }

  async function createProject(event) {
    event.preventDefault();
    const sourceVideoPath = $("sourceVideoPath").value.trim();
    const sourceDuration = numberValue("sourceDurationSeconds");
    if (!sourceVideoPath) {
      showMessage("视频路径不能为空");
      return;
    }
    const project = await requestJson("/api/projects", {
      method: "POST",
      body: JSON.stringify({
        source_video_path: sourceVideoPath,
        source_duration_seconds: sourceDuration,
      }),
    });
    await loadProjects();
    await selectProject(project.project_id);
    showMessage("项目已创建");
  }

  async function saveContext() {
    if (!state.selectedProject) {
      showMessage("先选择项目");
      return;
    }
    const projectId = state.selectedProject.project_id;
    state.selectedProject = await requestJson(`/api/projects/${projectId}/context`, {
      method: "PUT",
      body: JSON.stringify({
        context_packet: buildContextPacket(),
      }),
    });
    await loadProjects();
    renderProjects();
    showMessage("上下文已保存");
  }

  async function createVersion(event) {
    event.preventDefault();
    if (!state.selectedProject) {
      showMessage("先选择项目");
      return;
    }
    const targetDuration = numberValue("targetDurationSeconds");
    if (!targetDuration || targetDuration <= 0) {
      showMessage("目标时长必须大于 0");
      return;
    }
    if (
      state.selectedProject.source_duration_seconds &&
      targetDuration >= state.selectedProject.source_duration_seconds
    ) {
      showMessage("目标时长必须小于原视频时长");
      return;
    }
    const projectId = state.selectedProject.project_id;
    const version = await requestJson(`/api/projects/${projectId}/versions`, {
      method: "POST",
      body: JSON.stringify({
        target_duration_seconds: targetDuration,
        audio_mode: $("audioMode").value,
        voice_clone_id: $("voiceCloneId").value.trim(),
        bgm_path: $("bgmPath").value.trim(),
        voiceover_speed: numberValue("voiceoverSpeed") || 1.0,
        voiceover_volume: numberValue("voiceoverVolume") || 1.0,
        bgm_volume: numberValue("bgmVolume") || 0,
        subtitle_language: $("subtitleLanguage").value,
        aspect_ratio: $("aspectRatio").value,
        variant_goal: $("variantGoal").value.trim() || "manual",
      }),
    });
    await loadVersions(projectId);
    state.selectedVersion = version;
    renderVersions();
    setActionState();
    showMessage("版本已创建");
  }

  async function refreshActiveJob(projectId, jobId) {
    state.activeJob = await requestJson(`/api/projects/${projectId}/jobs/${jobId}`);
    await loadJobs(projectId);
    if (["done", "failed", "cancelled"].includes(state.activeJob.status)) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      showMessage(`渲染结束：${state.activeJob.status}`);
    }
  }

  function startPolling(projectId, jobId) {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
    }
    state.pollTimer = setInterval(() => {
      refreshActiveJob(projectId, jobId).catch((error) => showMessage(error.message));
    }, 3000);
  }

  async function startRender(event) {
    event.preventDefault();
    if (!state.selectedProject || !state.selectedVersion) {
      showMessage("先选择项目和版本");
      return;
    }
    const projectId = state.selectedProject.project_id;
    const versionId = state.selectedVersion.version_id;
    const job = await requestJson(`/api/projects/${projectId}/versions/${versionId}/render`, {
      method: "POST",
      body: JSON.stringify({
        tts_mode: $("ttsMode").value,
        require_llm: $("requireLlm").checked,
        force_script: $("forceScript").checked,
        force_review: $("forceReview").checked,
        force_humanize: $("forceHumanize").checked,
        force_tts: $("forceTts").checked,
        no_fit_duration: false,
      }),
    });
    state.activeJob = job;
    await loadJobs(projectId);
    startPolling(projectId, job.job_id);
    showMessage("渲染任务已开始");
  }

  function bindEvents() {
    $("projectForm").addEventListener("submit", (event) => {
      createProject(event).catch((error) => showMessage(error.message));
    });
    $("saveContextButton").addEventListener("click", () => {
      saveContext().catch((error) => showMessage(error.message));
    });
    $("versionForm").addEventListener("submit", (event) => {
      createVersion(event).catch((error) => showMessage(error.message));
    });
    $("renderForm").addEventListener("submit", (event) => {
      startRender(event).catch((error) => showMessage(error.message));
    });
  }

  async function init() {
    bindEvents();
    const health = await requestJson("/api/health");
    $("apiStatus").textContent = `${health.service}: ${health.status}`;
    await loadProjects();
    setActionState();
  }

  document.addEventListener("DOMContentLoaded", () => {
    init().catch((error) => {
      $("apiStatus").textContent = error.message;
      showMessage(error.message);
    });
  });
})();
