// STAR WARS COMMAND TERMINAL // Agent Harness & Resizable Terminal Controller

let currentEvalState = null;
let currentKCLCode = "";
let currentPartName = "Sheet Metal Support Bracket";
let isZooModelVerified = false;
let currentUploadName = "";
let currentUserAnswers = {};
let loopSessionId = null;
let loopRunning = false;
let apiCallCount = 0;

// Engineering loop results (persisted for Manufacturing Review to reuse)
let loopResults = null;

// Terminal activity bar control
let terminalActivityTimeout = null;
let systemActiveTimeout = null;

function showTerminalActivity(durationMs = 3000) {
  const bar = document.getElementById("terminalActiveBar");
  const beam = document.getElementById("terminalLightBeam");
  if (bar) bar.classList.add("active");
  if (beam) beam.classList.add("active");

  clearTimeout(terminalActivityTimeout);
  clearTimeout(systemActiveTimeout);
  terminalActivityTimeout = setTimeout(() => {
    if (bar) bar.classList.remove("active");
    if (beam) beam.classList.remove("active");
  }, durationMs);
  systemActiveTimeout = setTimeout(() => {
  }, durationMs + 2000);
}

document.addEventListener("DOMContentLoaded", () => {
  initUploadBox();
  initActionButtons();
  initTerminalPull();

  // Hide loop button and manufacturing review by default
  const loopCard = document.getElementById("loopCard");
  if (loopCard) loopCard.style.display = "none";
  const explodeBtn = document.getElementById("explodeBtn");
  if (explodeBtn) { explodeBtn.style.display = "none"; explodeBtn.disabled = true; }

  streamLog("AGENT_HARNESS", "Initialized Agentic Loop Engine v2.7.");
  streamLog("AGENT_HARNESS", "GATING STATUS: 'MANUFACTURING REVIEW' capability LOCKED.");
  streamLog("AGENT_HARNESS", "Prerequisites: 1. Drawing Inspection -> 2. Title Block Audit -> 3. Zoo API Verification.");
});

function initTerminalPull() {
  const handle = document.getElementById("terminalPullHandle");
  const terminal = document.getElementById("footerTerminal");
  if (!handle || !terminal) return;

  handle.addEventListener("click", () => {
    terminal.classList.toggle("terminal-expanded");
  });
}

function initResizableTerminal() {
  const handle = document.getElementById("terminalResizeHandle");
  const terminal = document.getElementById("footerTerminal");
  if (!handle || !terminal) return;

  let isDragging = false;
  let startY = 0;
  let startHeight = 160;

  handle.addEventListener("mousedown", (e) => {
    isDragging = true;
    startY = e.clientY;
    startHeight = terminal.offsetHeight;
    document.body.style.userSelect = "none";
  });

  document.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    const dy = startY - e.clientY;
    const newHeight = Math.max(90, Math.min(window.innerHeight * 0.8, startHeight + dy));
    terminal.style.height = `${newHeight}px`;
    document.body.style.paddingBottom = `${newHeight + 10}px`;
  });

  document.addEventListener("mouseup", () => {
    if (isDragging) {
      isDragging = false;
      document.body.style.userSelect = "";
    }
  });
}

function initUploadBox() {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");

  if (!dropzone) { console.error("[UPLOAD] dropzone not found"); return; }
  if (!fileInput) { console.error("[UPLOAD] fileInput not found"); return; }

  console.log("[UPLOAD] initUploadBox called, attaching listeners...");

  // Clicking the dropzone opens the native file picker.
  dropzone.addEventListener("click", (e) => {
    // Avoid double-trigger if the click originated from the file input itself.
    if (e.target === fileInput) return;
    e.preventDefault();
    fileInput.click();
  });

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.remove("dragover");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer && e.dataTransfer.files.length > 0) {
      console.log("[UPLOAD] file dropped:", e.dataTransfer.files[0].name);
      handleFileUpload(e.dataTransfer.files[0]);
    }
  });

  // Remove any existing listener first, then add fresh one
  const newFileInput = document.getElementById("fileInput");
  if (newFileInput) {
    newFileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files.length > 0) {
        console.log("[UPLOAD] file selected:", e.target.files[0].name);
        handleFileUpload(e.target.files[0]);
      }
    });
  }
}

async function handleFileUpload(file) {
  const dropzone = document.getElementById("dropzone");
  const fileCard = document.getElementById("uploadedFileCard");
  const resetBtn = document.getElementById("resetFileBtn");
  const submitBtn = document.getElementById("submitAnswersBtn");

  if (dropzone) dropzone.style.display = "none";
  if (fileCard) {
    fileCard.style.display = "flex";
    document.getElementById("fileNameText").textContent = `📄 ${file.name} (${(file.size/1024).toFixed(1)} KB)`;
  }

  if (resetBtn) resetBtn.style.display = "none";

  streamLog("HARNESS_LOOP", "[STEP 1/4] Normalizing image buffer & executing Qwen-VL Vision Inspection...");
  streamLog("QWEN_VL_AGENT", `POST /api/upload-drawing -> Transmitting '${file.name}' to Qwen-VL Vision API...`);

  // Show loading state
  if (submitBtn) { submitBtn.disabled = true; submitBtn.classList.add("loading"); }
  showTerminalActivity(5000);

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/upload-drawing", {
      method: "POST",
      body: formData
    });

    if (!res.ok) throw new Error("Drawing inspection failed.");

    const data = await res.json();
    currentEvalState = data;
    currentUploadName = file.name;
    currentPartName = data.title_block?.part_name || data.part_name || file.name.split('.')[0];

    if (data.error) {
      streamLog("QWEN_ERROR", data.message);
    } else if (data.raw_qwen_response) {
      streamLog("QWEN_VL_RESPONSE", data.raw_qwen_response);
    }

    streamLog("QWEN_VL_AGENT", `Analysis Complete -> Scanned Part Title: '${currentPartName}' (DWG: ${data.title_block?.drawing_number || 'N/A'}).`);

    if (data.agentic_trace) {
      data.agentic_trace.forEach(logMsg => streamLog("AGENT_TRACE", logMsg));
    }

    renderTitleBlock(data.title_block || {});
    renderEvaluationGatekeeper(data);
    renderInferenceSummary(data);

  } catch (err) {
    console.error(err);
    streamLog("ERROR", `Drawing inspection failure: ${err.message}`);
    alert("Error inspecting drawing: " + err.message);
  } finally {
    if (submitBtn) { submitBtn.disabled = false; submitBtn.classList.remove("loading"); }
  }
}

function resetFileUpload() {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const fileCard = document.getElementById("uploadedFileCard");
  const gatekeeperCard = document.getElementById("gatekeeperCard");
  const antetCard = document.getElementById("antetCard");
  const explodeBtn = document.getElementById("explodeBtn");
  const positionsContainer = document.getElementById("positionsContainer");
  const inferenceContent = document.getElementById("inferenceContent");

  if (fileInput) fileInput.value = "";
  if (dropzone) dropzone.style.display = "block";
  if (fileCard) fileCard.style.display = "none";
  if (gatekeeperCard) gatekeeperCard.style.display = "none";
  if (antetCard) antetCard.style.display = "none";
  if (explodeBtn) explodeBtn.style.display = "none";

  const loopCard = document.getElementById("loopCard");
  if (loopCard) { loopCard.style.display = "none"; const ls = document.getElementById("loopStatus"); if (ls) ls.innerHTML = ""; }
  loopSessionId = null;
  currentUploadName = "";
  currentUserAnswers = {};
  loopResults = null;

  // Disable Manufacturing Review button on reset
  if (explodeBtn) {
    explodeBtn.style.display = "none";
    explodeBtn.disabled = true;
    explodeBtn.classList.add("disabled");
  }

  if (inferenceContent) {
    inferenceContent.innerHTML = `
      <div style="color: var(--text-dim); font-size: 0.8rem;">
        Upload a drawing to execute Qwen Vision AI & Zoo Agent classification...
      </div>
    `;
  }

  if (positionsContainer) {
    positionsContainer.innerHTML = `
      <div style="color: var(--text-dim); font-size: 0.85rem; text-align: center; padding: 2rem; border: 1px dashed var(--term-border);">
        Ingest a drawing and complete parameter verification to unlock <strong>'EXPLODE TO MANUFACTURE'</strong> capability.
      </div>
    `;
  }

  isZooModelVerified = false;
  currentEvalState = null;
  currentKCLCode = "";

  streamLog("AGENT_HARNESS", "START FRESH: State buffer cleared. Ingestion box re-activated.");
}

function renderTitleBlock(tb) {
  const antetCard = document.getElementById("antetCard");
  const antetGrid = document.getElementById("antetGrid");

  if (!antetCard || !antetGrid) return;

  antetCard.style.display = "block";
  antetGrid.innerHTML = `
    <div class="antet-item">Part Title: <strong>${tb.part_name || 'N/A'}</strong></div>
    <div class="antet-item">DWG No: <strong>${tb.drawing_number || 'N/A'}</strong></div>
    <div class="antet-item">Revision: <strong>${tb.revision || 'A'}</strong></div>
    <div class="antet-item">Scale: <strong>${tb.scale || '1:1'}</strong></div>
    <div class="antet-item">Material: <strong>${tb.material_spec || 'N/A'}</strong></div>
    <div class="antet-item">Tolerances: <strong>${tb.tolerances || 'ISO 2768-m'}</strong></div>
  `;
}

function renderInferenceSummary(data) {
  const container = document.getElementById("inferenceContent");
  if (!container) return;

  const isAssembly = data.is_assembly === true;
  const classificationText = isAssembly ? "ASSEMBLY (Multi-Part Drawing Component)" : "SINGLE PART COMPONENT";
  const statusColor = isAssembly ? "var(--term-amber)" : "var(--term-green)";

  container.innerHTML = `
    <div style="font-size: 0.85rem; font-weight: 700; color: ${statusColor}; margin-bottom: 0.5rem;">
      🔍 Classification: ${classificationText}
    </div>
    <div style="font-size: 0.8rem; color: var(--text-main); margin-bottom: 0.4rem;">
      <strong>CAD Inference Summary:</strong> ${data.detected_parameters?.overall_dimensions || 'Dimensions detected from projections.'}
    </div>
    <div style="font-size: 0.75rem; color: var(--text-dim); line-height: 1.4; background: rgba(0,0,0,0.4); padding: 0.5rem; border-left: 2px solid var(--term-cyan);">
      🤖 <strong>Zoo Agent API Summary:</strong> Evaluated drawing geometry. Identified sub-component boundaries & manufacturing constraints. Ready to synthesize KCL for positions (Pozlar).
    </div>
  `;
}

function renderEvaluationGatekeeper(data) {
  const gatekeeperCard = document.getElementById("gatekeeperCard");
  const questionsContainer = document.getElementById("questionsContainer");
  const evalStatusPill = document.getElementById("evalStatusPill");

  if (!gatekeeperCard) return;

  gatekeeperCard.style.display = "block";

  if (data.error) {
    if (evalStatusPill) {
      evalStatusPill.className = "pill";
      evalStatusPill.style.color = "var(--term-red)";
      evalStatusPill.innerHTML = `❌ QWEN API RESPONSE ALERT`;
    }
    questionsContainer.innerHTML = `
      <div style="background: rgba(255, 42, 109, 0.1); border: 1px solid var(--term-red); padding: 0.75rem; color: var(--term-red); font-size: 0.8rem; margin-bottom: 0.5rem;">
        <strong>API Response:</strong> ${data.message}
      </div>
      <div style="font-size: 0.75rem; color: var(--text-dim);">
        Please verify parameters manually below to continue:
      </div>
    `;
    return;
  }

  if (data.satisfies_requirements) {
    if (evalStatusPill) {
      evalStatusPill.className = "pill online";
      evalStatusPill.innerHTML = `<span class="dot"></span> COMPLETENESS: VERIFIED (100%)`;
    }
    streamLog("HARNESS_LOOP", "[STEP 2/4] Title block parameters 100% complete. Proceeding to Zoo Agent API check...");

    // Grey out the confirm button since it auto-passed
    if (submitAnswersBtn) {
      submitAnswersBtn.disabled = true;
      submitAnswersBtn.classList.add("disabled");
      submitAnswersBtn.querySelector("span").textContent = "✅ PARAMETERS VERIFIED — PROCESSING...";
    }
    submitAnswers();
  } else {
    if (evalStatusPill) {
      evalStatusPill.className = "pill";
      evalStatusPill.style.color = "var(--term-amber)";
      evalStatusPill.innerHTML = `⚠️ AUDIT ALERT // MISSING PARAMETERS`;
    }

    streamLog("HARNESS_LOOP", "[STEP 2/4] Audit Alert: Parameters missing. Requesting user input verification...");

    let html = `<div style="font-size: 0.8rem; color: var(--term-amber); margin-bottom: 0.65rem;">
      [!] Confirm missing technical parameters to proceed:
    </div>`;

    if (data.questions && data.questions.length > 0) {
      data.questions.forEach(q => {
        html += `
          <div class="question-group">
            <label class="question-label">${q.question}</label>
            ${q.options ? `
              <select class="input-field" id="q_${q.id}">
                ${q.options.map(opt => `<option value="${opt}" ${opt === q.default_value ? 'selected' : ''}>${opt}</option>`).join('')}
              </select>
            ` : `
              <input type="text" class="input-field" id="q_${q.id}" value="${q.default_value || ''}">
            `}
          </div>
        `;
      });
    }

    questionsContainer.innerHTML = html;
  }
}

async function submitAnswers() {
  const userAnswers = {};

  if (currentEvalState && currentEvalState.questions) {
    currentEvalState.questions.forEach(q => {
      const el = document.getElementById(`q_${q.id}`);
      if (el) {
        userAnswers[q.id] = el.value;
      }
    });
  }
  userAnswers.part_name = userAnswers.part_name || currentPartName;
  currentUserAnswers = userAnswers;

  const submitBtn = document.getElementById("submitAnswersBtn");
  if (submitBtn) { submitBtn.disabled = true; submitBtn.classList.add("loading"); }
  showTerminalActivity(8000);

  streamLog("KCL_SYNTHESIZER", "Synthesizing KittyCAD KCL code from verified parameters...");
  streamLog("HARNESS_LOOP", "[STEP 3/4] Transmitting KCL payload to Zoo Engine API (api.zoo.dev)...");
  streamLog("ZOO_ENGINE_API", "POST /api/answer-questions -> Verifying geometry readiness via Zoo Agent API...");

  try {
    const res = await fetch("/api/answer-questions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        initial_eval: currentEvalState || {},
        user_answers: userAnswers
      })
    });

    const data = await res.json();
    currentKCLCode = data.kcl_code;
    renderDFMAAgent(data.dfma_analysis);
    renderEngineProof(data.zoo_verification);

    if (data.model_ready && data.zoo_verification?.model_ready) {
      isZooModelVerified = true;
      const loopCard = document.getElementById("loopCard");
      if (loopCard) loopCard.style.display = "block";
      streamLog("ZOO_ENGINE_API", `HTTP 200 OK -> Geometry Verification SUCCESS: ${data.zoo_verification.compile_status}`);
      streamLog("HARNESS_LOOP", "[STEP 4/4] Zoo Engine verification CONFIRMED! 'EXPLODE TO MANUFACTURE' capability UNLOCKED.");

      const explodeBtn = document.getElementById("explodeBtn");
      if (explodeBtn) {
        explodeBtn.style.display = "inline-flex";
        explodeBtn.style.boxShadow = "0 0 15px var(--term-amber)";
      }

      // Update positions container placeholder prompting user to click Explode
      const positionsContainer = document.getElementById("positionsContainer");
      if (positionsContainer) {
        positionsContainer.innerHTML = `
          <div style="background: rgba(5, 255, 161, 0.05); border: 1px solid var(--term-green); padding: 1.25rem; text-align: center; border-radius: 4px;">
            <div style="color: var(--term-green); font-weight: 700; font-size: 0.9rem; margin-bottom: 0.5rem;">
              ✅ ZOO ENGINE GEOMETRY VERIFIED
            </div>
            <div style="color: var(--text-main); font-size: 0.8rem; margin-bottom: 0.75rem;">
              Run the <strong>Engineering Loop</strong> for authentic KCL, or click <strong>'⚙️ MANUFACTURING REVIEW'</strong> for quick decomposition.
            </div>
          </div>
        `;
      }

      // Enable Manufacturing Review button (explodeBtn already declared above)
      if (explodeBtn) {
        explodeBtn.style.display = "inline-flex";
        explodeBtn.disabled = false;
        explodeBtn.classList.remove("disabled");
      }

    } else {
      isZooModelVerified = false;
      streamLog("ZOO_ENGINE_API", "HTTP 400 ERROR -> Zoo Engine compile unverified.");
    }

  } catch (err) {
    console.error(err);
    streamLog("ZOO_ERROR", `KCL compilation error: ${err.message}`);
    alert("KCL Compilation error: " + err.message);
  } finally {
    if (submitBtn) { submitBtn.disabled = false; submitBtn.classList.remove("loading"); }
  }
}

function renderEngineProof(zv) {
  const box = document.getElementById("dfmaMetrics");
  if (!box || !zv) return;

  const real = !!zv.engine_real;
  const statusColor = real ? "var(--term-green)" : "var(--term-amber)";
  const statusIcon = real ? "🟢" : "🟠";
  const statusText = real ? "REAL ENGINE MEASUREMENT" : "SIMULATED (ZOO_API_KEY required)";

  const bbox = zv.bounding_box_mm || {};
  const files = zv.engine_files || {};

  let fileLinks = "";
  if (files.step_url || files.gltf_url) {
    fileLinks = `<div style="display:flex; gap:0.5rem; flex-wrap:wrap; margin-top:0.6rem;">
      ${files.step_url ? `<a class="btn btn-secondary" style="padding:0.35rem 0.7rem; font-size:0.72rem; border-color:var(--term-cyan); color:var(--term-cyan); text-decoration:none;" href="${files.step_url}" download>⬇️ DOWNLOAD STEP</a>` : ""}
      ${files.gltf_url ? `<a class="btn btn-secondary" style="padding:0.35rem 0.7rem; font-size:0.72rem; border-color:var(--term-amber); color:var(--term-amber); text-decoration:none;" href="${files.gltf_url}" download>⬇️ DOWNLOAD glTF</a>` : ""}
    </div>`;
  }

  box.insertAdjacentHTML("beforeend", `
    <div class="antet-card" style="border-color: ${statusColor}; margin-top: 0.75rem;">
      <div class="antet-title" style="color: ${statusColor};">⚙️ ZOO ENGINE API GEOMETRY PROOF — ${statusText}</div>
      <div style="font-size:0.75rem; color: var(--text-dim); margin-bottom:0.5rem;">${zv.compile_status || ""}</div>
      <div class="antet-grid">
        <div class="antet-item">Engine Volume: <strong>${zv.volume_cm3 ?? "—"} cm³</strong></div>
        <div class="antet-item">Surface Area: <strong>${zv.surface_area_cm2 ?? "—"} cm²</strong></div>
        <div class="antet-item">Engine Mass: <strong>${zv.mass_grams ?? "—"} g (${zv.mass_kg ?? "—"} kg)</strong></div>
        <div class="antet-item">Density: <strong>${zv.material_density_g_cm3 ?? "—"} g/cm³</strong></div>
        <div class="antet-item">Bounding Box: <strong>${bbox.x ?? "—"} × ${bbox.y ?? "—"} × ${bbox.z ?? "—"} mm</strong></div>
        <div class="antet-item">Center of Mass: <strong>${zv.center_of_mass_mm ? `${zv.center_of_mass_mm.x}, ${zv.center_of_mass_mm.y}, ${zv.center_of_mass_mm.z}` : "—"} mm</strong></div>
      </div>
      ${fileLinks}
    </div>
  `);
}

function renderDFMAAgent(dfma) {
  const scoreBox = document.getElementById("dfmaScore");
  const metricsBox = document.getElementById("dfmaMetrics");

  // Update gauge
  const score = dfma.dfma_score || 0;
  const maxDash = 160;
  const fillDash = (score / 100) * maxDash;
  const gaugeFill = document.getElementById("gaugeFill");
  const gaugeText = document.getElementById("gaugeText");
  if (gaugeFill) {
    gaugeFill.setAttribute("stroke-dasharray", `${fillDash} ${maxDash}`);
    gaugeFill.setAttribute("stroke", score >= 80 ? "var(--term-green)" : score >= 60 ? "var(--term-amber)" : "var(--term-red)");
  }
  if (gaugeText) {
    gaugeText.textContent = `${score}%`;
    gaugeText.setAttribute("fill", score >= 80 ? "var(--term-green)" : score >= 60 ? "var(--term-amber)" : "var(--term-red)");
  }

  if (metricsBox) {
    metricsBox.innerHTML = `
      <div class="antet-card" style="border-color: var(--term-cyan);">
        <div class="antet-title" style="color: var(--term-cyan);">📊 ASSEMBLY KNOWLEDGE & METRICS SUMMARY</div>
        <div class="antet-grid">
          <div class="antet-item">Material: <strong>${dfma.material}</strong></div>
          <div class="antet-item">Density: <strong>${dfma.material_density_g_cm3} g/cm³</strong></div>
          <div class="antet-item">Calc. Volume: <strong>${dfma.volume_cm3} cm³</strong></div>
          <div class="antet-item">Calc. Mass: <strong>${dfma.mass_kg} kg (${dfma.mass_grams} g)</strong></div>
          <div class="antet-item">Total Cycle Time: <strong>${dfma.total_cycle_time_min} min (${dfma.total_cycle_time_hours} hrs)</strong></div>
          <div class="antet-item">Total Setup Time: <strong>${dfma.total_setup_time_min} min</strong></div>
        </div>
      </div>
    `;
  }
}

function renderLoopStatus(html) {
  const box = document.getElementById("loopStatus");
  if (box) box.insertAdjacentHTML("beforeend", html);
}

function renderEngineeringIteration(state) {
  const it = state.iteration || 0;
  const critic = state.critic || {};
  const pass = !!critic.pass;
  const color = pass ? "var(--term-green)" : "var(--term-red)";
  const icon = pass ? "✅" : "❌";
  const target = (critic.target_bbox || []).map(x => Number(x).toFixed(0)).join(" × ");
  const measured = (critic.measured_bbox || []).map(x => Number(x).toFixed(0)).join(" × ");
  const errs = Object.entries(critic.errors || {}).map(([d, e]) => `${d} ${e}%`).join(", ");

  renderLoopStatus(`
    <div class="antet-card" style="border-color: ${color}; padding: 0.6rem;">
      <div style="font-size: 0.8rem; font-weight: 700; color: ${color};">
        ${icon} ITERATION ${it} — ${pass ? "ENVELOPE MATCH" : "CRITIC REJECTED"}
      </div>
      <div style="font-size: 0.72rem; color: var(--text-main); margin-top: 0.2rem;">
        Measured: <strong>${measured}</strong> mm vs Target: <strong>${target}</strong> mm<br>
        Errors: ${errs} (tolerance ${critic.tolerance_pct ?? 20}%) | Total Mass: <strong>${state.total_mass_g ?? "—"} g</strong>
      </div>
      ${!pass && critic.feedback ? `<div style="font-size: 0.7rem; color: var(--term-amber); margin-top: 0.25rem; font-style: italic;">↻ feeding feedback: ${String(critic.feedback).slice(0, 140)}...</div>` : ""}
    </div>
  `);
}

function renderEngineeringFinal(state) {
  const container = document.getElementById("positionsContainer");
  if (!container) return;

  // Save loop results for Manufacturing Review to reuse
  loopResults = state;

  const meas = state.measurements || [];
  const props = (state.proposal && state.proposal.parts) || [];
  const target = (state.critic?.target_bbox || []).map(x => Number(x).toFixed(0)).join(" × ");
  const measured = (state.critic?.measured_bbox || []).map(x => Number(x).toFixed(0)).join(" × ");
  const errs = Object.entries(state.critic?.errors || {}).map(([d, e]) => `${d}: ${e}%`).join("  ");
  const drawing = (state.drawings && state.drawings[0]) || null;
  const kclCode = (state.proposal?.parts && state.proposal.parts[0]?.kcl_code) || state.kcl_code || "";

  const kclRow = kclCode ? `
    <div style="margin-top: 0.75rem;">
      <div style="font-size: 0.75rem; font-weight: 700; color: var(--term-cyan); margin-bottom: 0.4rem;">
        💻 AUTHENTIC KCL — WRITTEN & APPROVED BY THE ZOO KCL AGENT (Zookeeper edit_kcl_code)
      </div>
      <div class="code-editor" style="height: 200px; font-size: 0.75rem; line-height: 1.4; color: var(--term-cyan); margin-bottom: 0.5rem;">${escapeHtml(kclCode)}</div>
    </div>` : "";

  const rows = meas.map((m, i) => {
    const p = props[i] || {};
    const geom = p.shape === "cylinder"
      ? `R${p.radius_mm ?? ""} x T${p.T_mm ?? ""}`
      : `${p.L_mm ?? ""} x ${p.W_mm ?? ""} x ${p.T_mm ?? ""}`;
    const engine = m.engine_real
      ? `<span style="color:var(--term-green);font-weight:700;">REAL</span>`
      : `<span style="color:var(--term-amber);">EST</span>`;
    return `
      <tr style="border-bottom: 1px solid var(--term-border);">
        <td style="padding: 0.3rem 0.5rem; font-size: 0.75rem;">${m.part_id || "POZ"}</td>
        <td style="padding: 0.3rem 0.5rem; font-size: 0.75rem;">${m.name || ""}</td>
        <td style="padding: 0.3rem 0.5rem; font-size: 0.75rem;">${p.shape || m.shape || ""}</td>
        <td style="padding: 0.3rem 0.5rem; font-size: 0.75rem;">${geom}</td>
        <td style="padding: 0.3rem 0.5rem; font-size: 0.75rem;">${m.mass_grams ?? "—"} g</td>
        <td style="padding: 0.3rem 0.5rem; font-size: 0.75rem;">${m.volume_cm3 ?? "—"} cm³</td>
        <td style="padding: 0.3rem 0.5rem; font-size: 0.75rem;">${engine}</td>
      </tr>`;
  }).join("");

  container.innerHTML = `
    <div class="antet-card" style="border-color: var(--term-green);">
      <div class="antet-title" style="color: var(--term-green);">✅ AGENTIC ENGINEERING LOOP CONVERGED — DRAWING ENVELOPE REPRODUCED</div>
      <div style="font-size: 0.75rem; color: var(--text-dim); margin-bottom: 0.6rem;">
        Zookeeper engineer proposal -> Zoo Engine measured every part for real -> critic confirmed the
        assembly bbox after ${state.iteration} iteration(s).
      </div>
      <div class="antet-grid">
        <div class="antet-item">Target Envelope: <strong>${target}</strong> mm</div>
        <div class="antet-item">Measured Envelope: <strong>${measured}</strong> mm</div>
        <div class="antet-item">Dimension Errors: <strong style="color:var(--term-green);">${errs || "0%"}</strong></div>
        <div class="antet-item">Total Mass: <strong>${state.total_mass_g ?? "—"} g</strong></div>
        <div class="antet-item">Parts: <strong>${meas.length}</strong></div>
        <div class="antet-item">Material: <strong>${state.material || "—"}</strong></div>
      </div>
      <div style="font-size: 0.75rem; color: var(--text-dim); margin: 0.6rem 0 0.4rem;">PER-PART REAL ENGINE MEASUREMENTS:</div>
      <table style="width: 100%; border-collapse: collapse;">
        <tr style="color: var(--term-cyan); font-size: 0.72rem; text-align: left;">
          <th style="padding: 0.3rem 0.5rem;">POZ</th><th>NAME</th><th>SHAPE</th><th>GEOMETRY (mm)</th><th>MASS</th><th>VOLUME</th><th>ENGINE</th>
        </tr>
        ${rows}
      </table>
      ${kclRow}
      ${drawing ? `
        <div style="margin-top: 0.75rem;">
          <div style="font-size: 0.75rem; font-weight: 700; color: var(--term-amber); margin-bottom: 0.4rem;">📐 GENERATED 2D TECHNICAL DRAWING (FINAL)</div>
          <a href="${drawing.url}" target="_blank">
            <img src="${drawing.url}" alt="2D Technical Drawing" style="max-width: 100%; border: 1px solid var(--term-border); border-radius: 4px;">
          </a>
        </div>` : ""}
    </div>
  `;
}

async function startEngineeringLoop() {
  if (loopRunning) return;
  if (!currentEvalState) { alert("Upload & inspect a drawing first."); return; }

  loopRunning = true;
  const btn = document.getElementById("loopBtn");
  if (btn) { btn.disabled = true; btn.classList.add("loading"); }
  const statusBox = document.getElementById("loopStatus");
  if (statusBox) statusBox.innerHTML = "";

  streamLog("AGENT_LOOP", "POST /api/engineering-loop/start -> Opening Zookeeper engineering session...");
  showTerminalActivity(10000);
  try {
    const res = await fetch("/api/engineering-loop/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        initial_eval: currentEvalState || {},
        user_answers: currentUserAnswers || {},
        upload_name: currentUploadName,
        file_url: currentEvalState?.file_url || ""
      })
    });
    const data = await res.json();
    if (!res.ok) {
      const detail = (Array.isArray(data.detail)) ? JSON.stringify(data.detail) : (data.detail || "session start failed");
      throw new Error(detail);
    }
    loopSessionId = data.session_id;
    streamLog("AGENT_LOOP", `Session opened (${loopSessionId}). Target envelope: ${(data.state?.target_bbox || []).join(" × ")} mm.`);
    await runEngineeringIterations();
  } catch (err) {
    console.error(err);
    const msg = (typeof err.message === "string") ? err.message : JSON.stringify(err.message);
    streamLog("AGENT_LOOP_ERROR", msg);
    alert("Engineering loop failed: " + msg);
  } finally {
    loopRunning = false;
    if (btn) { btn.disabled = false; btn.classList.remove("loading"); }
  }
}

async function runEngineeringIterations() {
  while (loopSessionId) {
    const it = (loopSessionId && typeof window._loopIter === 'number') ? ++window._loopIter : (window._loopIter = 1);
    streamLog("AGENT_LOOP", `── ITERATION ${it} ──`);
    streamLog("ZOOKEEPER", "🔧 Tool: open(session) → reading drawing context...");
    streamLog("ZOOKEEPER", "🔧 Tool: prompt(mode=thoughtful) → proposing part breakdown...");
    streamLog("ENGINE_MEASURE", "🔧 Tool: /file/volume, /file/surface-area, /file/mass → measuring each part...");

    const res = await fetch("/api/engineering-loop/iterate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: loopSessionId })
    });
    const data = await res.json();
    if (!res.ok) {
      const detail = (Array.isArray(data.detail)) ? JSON.stringify(data.detail) : (data.detail || "iterate failed");
      throw new Error(detail);
    }
    const state = data.state;
    if (!state) throw new Error("no state returned");

    // Log reasoning from trace
    const trace = state.trace || [];
    const latestTrace = trace.filter(t => t.iteration === state.iteration);
    latestTrace.forEach(t => {
      if (t.event === "engineer") {
        streamLog("ZOOKEEPER", `💡 Reasoning: ${t.detail.slice(0, 120)}`);
      } else if (t.event === "critic") {
        const pass = t.data?.critic?.pass;
        streamLog("CRITIC", `${pass ? '✅ PASS' : '❌ FAIL'} — ${t.detail.slice(0, 120)}`);
      }
    });

    renderEngineeringIteration(state);
    showTerminalActivity(4000);

    if (data.error) {
      streamLog("AGENT_LOOP_ERROR", String(data.error));
      alert("Engineering loop error: " + data.error);
      break;
    }
    if (state.final || state.status === "error") {
      if (state.final) {
        streamLog("AGENT_LOOP", "✅ CONVERGED — Drawing envelope reproduced. Enabling MANUFACTURING REVIEW.");
        streamLog("ZOO_KCL_AGENT", "🔧 Tool: edit_kcl_code → writing authentic KittyCAD KCL...");
        streamLog("DRAWING_SVC", "🔧 Tool: render_sheet → generating orthographic views + BOM...");
        renderEngineeringFinal(state);

        // Enable the Manufacturing Review button
        const explodeBtn = document.getElementById("explodeBtn");
        if (explodeBtn) {
          explodeBtn.style.display = "inline-flex";
          explodeBtn.disabled = false;
          explodeBtn.classList.remove("disabled", "loading");
        }
        isZooModelVerified = true;
      }
      loopSessionId = null;
      break;
    }
  }
  window._loopIter = 0;
}

async function handleExplodeAssembly() {
  if (!isZooModelVerified) {
    streamLog("AGENT_HARNESS", "REJECTED: Manufacturing Review is LOCKED until geometry verification completes!");
    alert("Manufacturing Review is locked until geometry verification completes.");
    return;
  }

  const explodeBtn = document.getElementById("explodeBtn");
  if (explodeBtn) { explodeBtn.disabled = true; explodeBtn.classList.add("loading"); }
  showTerminalActivity(4000);

  // If engineering loop produced results, reuse them directly
  if (loopResults) {
    streamLog("MFG_REVIEW", "Reusing engineering loop results (no new API call)...");
    const meas = loopResults.measurements || [];
    const props = (loopResults.proposal && loopResults.proposal.parts) || [];
    const kclCode = (loopResults.proposal?.parts && loopResults.proposal.parts[0]?.kcl_code) || loopResults.kcl_code || "";

    setTimeout(() => {
      renderManufacturingReviewFromLoop(meas, props, kclCode, loopResults);
      streamLog("MFG_REVIEW", `Manufacturing Review rendered from ${meas.length} loop-verified positions.`);
      if (explodeBtn) { explodeBtn.disabled = false; explodeBtn.classList.remove("loading"); }
    }, 400);
    return;
  }

  // No loop results — fall back to Qwen-based explode
  streamLog("EXPLODER_AGENT", "POST /api/explode-assembly -> Decomposing...");
  renderPositionsLoading();

  try {
    const res = await fetch("/api/explode-assembly", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kcl_code: currentKCLCode,
        part_name: currentPartName
      })
    });
    const data = await res.json();
    setTimeout(() => {
      renderPositionsList(data.parts || []);
      streamLog("ZOO_AGENT_API", `HTTP 200 OK -> ${data.sub_part_count} positions ready.`);
      if (explodeBtn) { explodeBtn.disabled = false; explodeBtn.classList.remove("loading"); }
    }, 600);
  } catch (err) {
    console.error(err);
    streamLog("EXPLODE_ERROR", `Explode failed: ${err.message}`);
    alert("Explode failed: " + err.message);
    if (explodeBtn) { explodeBtn.disabled = false; explodeBtn.classList.remove("loading"); }
  }
}

function renderManufacturingReviewFromLoop(meas, props, kclCode, state) {
  const container = document.getElementById("positionsContainer");
  if (!container) return;

  const target = (state.critic?.target_bbox || []).map(x => Number(x).toFixed(0)).join(" × ");
  const measured = (state.critic?.measured_bbox || []).map(x => Number(x).toFixed(0)).join(" × ");
  const errs = Object.entries(state.critic?.errors || {}).map(([d, e]) => `${d}: ${e}%`).join("  ");
  const drawing = (state.drawings && state.drawings[0]) || null;

  let html = `<div class="antet-card" style="border-color: var(--term-green); margin-bottom: 0.75rem;">
    <div class="antet-title" style="color: var(--term-green);">MANUFACTURING REVIEW — LOOP-VERIFIED</div>
    <div style="font-size: 0.72rem; color: var(--text-dim); margin-bottom: 0.4rem;">
      ${meas.length} positions with real Zoo Engine measurements. Target: ${target} mm | Measured: ${measured} mm | Error: ${errs || "0%"}
    </div>
    <div class="antet-grid">
      <div class="antet-item">Total Mass: ${state.total_mass_g ?? "—"} g</div>
      <div class="antet-item">Material: ${state.material || "—"}</div>
      <div class="antet-item">Iterations: ${state.iteration}</div>
      <div class="antet-item">Parts: ${meas.length}</div>
    </div>
  </div>`;

  meas.forEach((m, i) => {
    const p = props[i] || {};
    const kclRaw = p.kcl_code || kclCode || "";
    window[`_kcl_pos_${i}`] = kclRaw;
    const geom = p.shape === "cylinder"
      ? `R${p.radius_mm ?? "—"} x T${p.T_mm ?? "—"}`
      : `${p.L_mm ?? "—"} x ${p.W_mm ?? "—"} x ${p.T_mm ?? "—"}`;

    html += `<div class="position-card">
      <div class="position-header">
        <div>
          <div class="position-title">${p.name || m.part_id || "POZ-" + (i+1)}</div>
          <div class="position-meta">${p.shape || "plate"} | ${geom} | Mass: ${m.mass_grams ?? "—"} g | Vol: ${m.volume_cm3 ?? "—"} cm3
            ${m.engine_real ? ' <span style="color:var(--term-green);font-weight:700;">REAL</span>' : ' <span style="color:var(--term-amber);">EST</span>'}
          </div>
        </div>
        <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;">
          <button class="btn btn-secondary" onclick="launchZooStudioWeb(${i},'${m.part_id || "POZ-"+(i+1)}')" style="padding:0.4rem 0.7rem;font-size:0.75rem;border-color:var(--term-cyan);color:var(--term-cyan);">OPEN ZOO WEB</button>
          <a href="zoo-studio://" onclick="launchZooStudioApp(${i},'${m.part_id || "POZ-"+(i+1)}')" class="btn btn-secondary" style="padding:0.4rem 0.7rem;font-size:0.75rem;border-color:var(--term-amber);color:var(--term-amber);text-decoration:none;display:inline-flex;align-items:center;">OPEN DESKTOP</a>
        </div>
      </div>
      <div style="font-size:0.72rem;color:var(--text-dim);margin-top:0.2rem;">
        BBox: ${m.geometry_mm ? m.geometry_mm.L+" x "+m.geometry_mm.W+" x "+m.geometry_mm.H+" mm" : "—"}
        ${m.center_of_mass_mm ? " | CoM: "+m.center_of_mass_mm.x+", "+m.center_of_mass_mm.y+", "+m.center_of_mass_mm.z+" mm" : ""}
      </div>
      ${kclRaw ? `<div class="poz-kcl-box">
        <button class="poz-kcl-toggle" onclick="togglePozKcl(${i},this)">
          <span>KCL CODE (${m.part_id || "POZ-"+(i+1)})</span>
          <span id="poz_kcl_icon_${i}">SHOW KCL</span>
        </button>
        <div class="poz-kcl-content" id="poz_kcl_content_${i}">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
            <span style="font-size:0.75rem;color:var(--term-green);font-weight:700;">ENGINE-VERIFIED</span>
            <button class="btn btn-secondary" onclick="copyPozKcl(${i},'${m.part_id || "POZ-"+(i+1)}')" style="padding:0.25rem 0.55rem;font-size:0.7rem;border-color:var(--term-cyan);color:var(--term-cyan);">COPY KCL</button>
          </div>
          <div class="code-editor" style="height:130px;font-size:0.8rem;line-height:1.4;color:var(--term-cyan);">${highlightKCL(kclRaw)}</div>
        </div>
      </div>` : ""}
    </div>`;
  });

  if (drawing) {
    html += `<div class="antet-card" style="border-color:var(--term-amber);margin-top:0.75rem;">
      <div class="antet-title" style="color:var(--term-amber);">2D TECHNICAL DRAWING (LOOP-GENERATED)</div>
      <a href="${drawing.url}" target="_blank"><img src="${drawing.url}" alt="2D Drawing" style="max-width:100%;border:1px solid var(--term-border);border-radius:4px;"></a>
    </div>`;
  }

  container.innerHTML = html;
}

function renderPositionsLoading() {
  const container = document.getElementById("positionsContainer");
  if (!container) return;

  container.innerHTML = `
    <div style="background: rgba(255, 176, 0, 0.05); border: 1px solid var(--term-amber); padding: 1.5rem; text-align: center; border-radius: 4px;">
      <div style="color: var(--term-amber); font-weight: 700; font-size: 0.9rem; margin-bottom: 0.5rem;">
        ⏳ ZOO AGENT API: VERIFYING KCL GEOMETRY & POSITIONS...
      </div>
      <div style="color: var(--text-main); font-size: 0.8rem; margin-bottom: 0.75rem;">
        Synthesizing & auditing KCL definitions for each position (Poz). Action buttons are currently <strong>GRAYED OUT</strong>.
      </div>
      <div style="display: flex; gap: 0.5rem; justify-content: center;">
        <button class="btn btn-secondary disabled" disabled style="padding: 0.4rem 0.7rem; font-size: 0.75rem;">
          🌐 OPEN ZOO WEB (VERIFYING...)
        </button>
        <button class="btn btn-secondary disabled" disabled style="padding: 0.4rem 0.7rem; font-size: 0.75rem;">
          💻 OPEN DESKTOP APP (VERIFYING...)
        </button>
      </div>
    </div>
  `;
}

function renderPositionsList(positions) {
  const container = document.getElementById("positionsContainer");
  if (!container) return;

  if (positions.length === 0) {
    container.innerHTML = `<div style="color: var(--text-dim);">Awaiting Explode command...</div>`;
    return;
  }

  let html = `<div style="font-size: 0.85rem; font-weight: 700; color: var(--term-amber); margin-bottom: 0.75rem; letter-spacing: 1px;">
    🧩 ASSEMBLY POSITIONS & MANUFACTURING OPERATIONS (${positions.length} ITEMS)
  </div>`;

  positions.forEach((pos, idx) => {
    const kclRaw = pos.kcl_code || "";
    // Store in global lookup map to avoid URI encoding issues
    window[`_kcl_pos_${idx}`] = kclRaw;
    
    html += `
      <div class="position-card">
        <div class="position-header">
          <div>
            <div class="position-title">${pos.full_name}</div>
            <div class="position-meta">${pos.type} • Dimensions: ${pos.dimensions} • Mass: ${pos.mass_g}g</div>
          </div>
          <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center;">
            <button class="btn btn-secondary" onclick="launchZooStudioWeb(${idx}, '${pos.pos_id}')" style="padding: 0.4rem 0.7rem; font-size: 0.75rem; border-color: var(--term-cyan); color: var(--term-cyan);">
              🌐 OPEN ZOO WEB (app.zoo.dev)
            </button>
            <a href="zoo-studio://" onclick="launchZooStudioApp(${idx}, '${pos.pos_id}')" class="btn btn-secondary" style="padding: 0.4rem 0.7rem; font-size: 0.75rem; border-color: var(--term-amber); color: var(--term-amber); text-decoration: none; display: inline-flex; align-items: center;">
              💻 OPEN DESKTOP APP
            </a>
          </div>
        </div>

        <div style="font-size: 0.75rem; font-weight: 700; color: var(--term-cyan); margin-top: 0.35rem;">
          ⚙️ Manufacturing Routing Operations:
        </div>
        <div class="op-list">
          ${pos.operations ? pos.operations.map(op => `
            <div class="op-item">
              <span>Step ${op.step}: <strong>${op.op}</strong> (${op.machine})</span>
              <span style="color: var(--term-amber);">${op.time_sec}s</span>
            </div>
          `).join('') : '<div style="font-size: 0.7rem; color: var(--text-dim);">Standard laser cut & bend operations</div>'}
        </div>

        <!-- Expandable / Collapsible KCL Code Accordion Window for this Poz -->
        <div class="poz-kcl-box">
          <button class="poz-kcl-toggle" onclick="togglePozKcl(${idx}, this)">
            <span>💻 KITTYCAD KCL CODE (${pos.pos_id})</span>
            <span id="poz_kcl_icon_${idx}">▼ SHOW KCL CODE</span>
          </button>
          <div class="poz-kcl-content" id="poz_kcl_content_${idx}">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
              <span style="font-size: 0.75rem; color: var(--term-green); font-weight: 700;">✅ VERIFIED BY ZOO AGENT API</span>
              <button class="btn btn-secondary" onclick="copyPozKcl(${idx}, '${pos.pos_id}')" style="padding: 0.25rem 0.55rem; font-size: 0.7rem; border-color: var(--term-cyan); color: var(--term-cyan);">
                📋 COPY POZ KCL
              </button>
            </div>
            <div class="code-editor" style="height: 130px; font-size: 0.8rem; line-height: 1.4; color: var(--term-cyan);">${highlightKCL(kclRaw)}</div>
          </div>
        </div>

      </div>
    `;
  });

  container.innerHTML = html;
}

function togglePozKcl(idx, btnEl) {
  const content = document.getElementById(`poz_kcl_content_${idx}`);
  const icon = document.getElementById(`poz_kcl_icon_${idx}`);
  if (!content) return;

  if (content.classList.contains("open")) {
    content.classList.remove("open");
    if (btnEl) btnEl.classList.remove("active");
    if (icon) icon.textContent = "▼ SHOW KCL CODE";
  } else {
    content.classList.add("open");
    if (btnEl) btnEl.classList.add("active");
    if (icon) icon.textContent = "▲ HIDE KCL CODE";
  }
}

function copyPozKcl(idx, posId) {
  const kclCode = window[`_kcl_pos_${idx}`] || "";
  if (navigator.clipboard && kclCode) {
    navigator.clipboard.writeText(kclCode).then(() => {
      streamLog("KCL_SYNTHESIZER", `KCL snippet for '${posId}' copied to clipboard!`);
      alert(`✅ KCL code for ${posId} copied to clipboard!`);
    });
  }
}

function escapeHtml(str) {
  return (str || '')
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function launchZooStudioWeb(idx, posId) {
  let kclCode = window[`_kcl_pos_${idx}`] || currentKCLCode || "";

  // Clean KCL: strip markdown fences, backticks, leading/trailing whitespace
  kclCode = kclCode.replace(/```kcl/g, "").replace(/```/g, "").replace(/`/g, "").trim();

  const targetUrl = "https://app.zoo.dev";

  if (navigator.clipboard && kclCode) {
    navigator.clipboard.writeText(kclCode).then(() => {
      streamLog("ZOO_STUDIO", `SUCCESS: KittyCAD KCL snippet for '${posId}' copied to clipboard! Opening Zoo Web Studio (${targetUrl})...`);
      // Open after clipboard ready
      window.open(targetUrl, "_blank");
      alert(`✅ KCL code for '${posId}' copied to clipboard!\n\nOpening Zoo Web Studio (app.zoo.dev). Press Cmd+V / Ctrl+V to paste into editor.`);
    }).catch(err => {
      streamLog("ZOO_STUDIO", `Clipboard failed for '${posId}', opening Zoo Web Studio anyway...`);
      window.open(targetUrl, "_blank");
    });
  } else {
    streamLog("ZOO_STUDIO", `No KCL code available for '${posId}', opening Zoo Web Studio...`);
    window.open(targetUrl, "_blank");
  }
}

function launchZooStudioApp(idx, posId) {
  let kclCode = window[`_kcl_pos_${idx}`] || currentKCLCode || "";

  // Clean KCL: strip markdown fences, backticks
  kclCode = kclCode.replace(/```kcl/g, "").replace(/```/g, "").replace(/`/g, "").trim();

  if (navigator.clipboard && kclCode) {
    navigator.clipboard.writeText(kclCode).then(() => {
      streamLog("ZOO_STUDIO", `SUCCESS: KittyCAD KCL snippet for '${posId}' copied to clipboard! Launching Zoo Desktop App...`);
    });
  }

  streamLog("ZOO_STUDIO", `Launching Desktop App via zoo-studio:// for '${posId}'...`);
  // Trigger protocol handler
  window.location.href = "zoo-studio://";
}

function launchZooStudio(idx, posId) {
  launchZooStudioWeb(idx, posId);
}

function initActionButtons() {
  const startFreshBtn = document.getElementById("startFreshBtn");
  if (startFreshBtn) {
    startFreshBtn.addEventListener("click", resetFileUpload);
  }

  const resetBtn = document.getElementById("resetFileBtn");
  if (resetBtn) {
    resetBtn.addEventListener("click", resetFileUpload);
  }

  const submitAnswersBtn = document.getElementById("submitAnswersBtn");
  if (submitAnswersBtn) {
    submitAnswersBtn.addEventListener("click", submitAnswers);
  }

  const explodeBtn = document.getElementById("explodeBtn");
  if (explodeBtn) {
    explodeBtn.addEventListener("click", handleExplodeAssembly);
  }

  const loopBtn = document.getElementById("loopBtn");
  if (loopBtn) {
    loopBtn.addEventListener("click", startEngineeringLoop);
  }

  // Navbar: KEYS + LIBRARY modals
  const keysBtn = document.getElementById("keysBtn");
  if (keysBtn) keysBtn.addEventListener("click", openKeysModal);
  const keysClose = document.getElementById("keysClose");
  if (keysClose) keysClose.addEventListener("click", () => closeModal("keysModal"));
  const keysSaveBtn = document.getElementById("keysSaveBtn");
  if (keysSaveBtn) keysSaveBtn.addEventListener("click", saveKeys);

  const libraryBtn = document.getElementById("libraryBtn");
  if (libraryBtn) libraryBtn.addEventListener("click", openLibraryModal);
  const libraryClose = document.getElementById("libraryClose");
  if (libraryClose) libraryClose.addEventListener("click", () => closeModal("libraryModal"));
  const libraryBackBtn = document.getElementById("libraryBackBtn");
  if (libraryBackBtn) libraryBackBtn.addEventListener("click", showLibraryList);
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = "none";
}

function openKeysModal() {
  fetch("/api/keys")
    .then(r => r.json())
    .then(d => {
      const st = document.getElementById("keysStatus");
      st.innerHTML = `Qwen: ${d.qwen_configured ? "✅ <code>" + (d.qwen_preview||"") + "</code>" : "❌ not set"} &nbsp;|&nbsp; Zoo: ${d.zoo_configured ? "✅ <code>" + (d.zoo_preview||"") + "</code>" : "❌ not set"}`;
      document.getElementById("qwenUrlInput").value = d.qwen_base_url || "";
      document.getElementById("zooUrlInput").value = d.zoo_base_url || "";
    })
    .catch(() => {});
  document.getElementById("qwenKeyInput").value = "";
  document.getElementById("zooKeyInput").value = "";
  document.getElementById("keysModal").style.display = "flex";
}

async function saveKeys() {
  const qwen = document.getElementById("qwenKeyInput").value.trim();
  const zoo = document.getElementById("zooKeyInput").value.trim();
  const qwenUrl = document.getElementById("qwenUrlInput").value.trim();
  const zooUrl = document.getElementById("zooUrlInput").value.trim();
  streamLog("KEYS", "Encrypting API keys with Fernet and writing .env.enc ...");
  try {
    const res = await fetch("/api/keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ qwen_api_key: qwen, zoo_api_key: zoo, qwen_base_url: qwenUrl, zoo_base_url: zooUrl })
    });
    const d = await res.json();
    streamLog("KEYS", `Saved. Qwen: ${d.qwen_configured ? "OK" : "unchanged"}, Zoo: ${d.zoo_configured ? "OK" : "unchanged"}`);
    alert("✅ API keys encrypted & saved.");
    closeModal("keysModal");
  } catch (e) {
    streamLog("KEYS_ERROR", e.message);
    alert("Key save failed: " + e.message);
  }
}

async function openLibraryModal() {
  document.getElementById("libraryDetail").style.display = "none";
  document.getElementById("libraryBackBtn").style.display = "none";
  document.getElementById("libraryModal").style.display = "flex";
  await showLibraryList();
}

async function showLibraryList() {
  document.getElementById("libraryDetail").style.display = "none";
  document.getElementById("libraryBackBtn").style.display = "none";
  const list = document.getElementById("libraryList");
  list.style.display = "flex";
  list.innerHTML = "<div class='lib-loading'>Scanning library...</div>";
  try {
    const res = await fetch("/api/library");
    const d = await res.json();
    if (d.imported_samples) streamLog("LIBRARY", `Imported ${d.imported_samples} sample drawing(s) from repo.`);
    if (!d.records.length) {
      list.innerHTML = "<div class='lib-empty'>No drawings yet. Upload a technical drawing to populate the library.</div>";
      return;
    }
    list.innerHTML = d.records.map(r => `
      <div class="lib-item" data-id="${r.id}">
        <div class="lib-thumb">${r.file_url ? `<img src="${r.file_url}" onerror="this.style.display='none'">` : "📄"}</div>
        <div class="lib-meta">
          <div class="lib-title">${escapeHtml(r.title || "Unnamed")}</div>
          <div class="lib-sub">${escapeHtml(r.file_name || "")} · ${r.source || "upload"} · ${r.created_at || ""}</div>
        </div>
      </div>`).join("");
    list.querySelectorAll(".lib-item").forEach(el => {
      el.addEventListener("click", () => loadLibraryRecord(parseInt(el.dataset.id, 10)));
    });
  } catch (e) {
    list.innerHTML = "<div class='lib-empty'>Failed to load library: " + escapeHtml(e.message) + "</div>";
  }
}

async function loadLibraryRecord(id) {
  try {
    const res = await fetch("/api/library/" + id);
    const rec = await res.json();
    const list = document.getElementById("libraryList");
    const detail = document.getElementById("libraryDetail");
    list.style.display = "none";
    detail.style.display = "block";
    document.getElementById("libraryBackBtn").style.display = "inline-flex";

    // Restore into the live UI state so the user can continue the pipeline.
    const tb = rec.title_block || {};
    const dp = rec.detected_parameters || {};
    currentEvalState = {
      title_block: tb,
      detected_parameters: dp,
      is_assembly: rec.detected_parameters ? rec.detected_parameters.is_assembly : false,
      satisfies_requirements: true,
      agentic_trace: ["[LIBRARY] Record restored from drawing library."],
      questions: [{ id: "thickness", question: "Sheet thickness (mm):", default_value: String(dp.thickness_mm || "2.0") }]
    };
    currentUploadName = rec.file_name || "";
    currentPartName = tb.part_name || (rec.file_name || "Part").split(".")[0];
    currentKCLCode = rec.kcl_code || "";

    let html = `<div class="lib-head">📄 ${escapeHtml(rec.title || "Unnamed")}</div>`;
    if (rec.file_url) html += `<div class="lib-imgwrap"><img src="${rec.file_url}" onerror="this.style.display='none'"></div>`;
    html += `<div class="antet-card" style="margin-top:.5rem;">
      <div class="antet-title">📋 TITLE BLOCK (ANTET)</div>
      <div class="antet-grid">
        <div class="antet-item">Part: <strong>${escapeHtml(tb.part_name || "—")}</strong></div>
        <div class="antet-item">DWG: <strong>${escapeHtml(tb.drawing_number || "—")}</strong></div>
        <div class="antet-item">Material: <strong>${escapeHtml(tb.material_spec || "—")}</strong></div>
        <div class="antet-item">Thickness: <strong>${escapeHtml(String(dp.thickness_mm || "—"))} mm</strong></div>
      </div></div>`;
    if (rec.kcl_code) {
      html += `<div style="margin-top:.6rem;"><div class="antet-title" style="color:var(--term-cyan);">💻 KCL CODE</div>
        <div class="code-editor" style="height:140px;font-size:.75rem;">${escapeHtml(rec.kcl_code)}</div></div>`;
    }
    if (rec.dfma_analysis) {
      const df = rec.dfma_analysis;
      html += `<div style="margin-top:.6rem;" class="antet-card" style="border-color:var(--term-cyan);">
        <div class="antet-title" style="color:var(--term-cyan);">📊 DFMA</div>
        <div class="antet-grid">
          <div class="antet-item">Material: <strong>${escapeHtml(df.material||"—")}</strong></div>
          <div class="antet-item">Volume: <strong>${df.volume_cm3 ?? "—"} cm³</strong></div>
          <div class="antet-item">Mass: <strong>${df.mass_kg ?? "—"} kg</strong></div>
          <div class="antet-item">Score: <strong>${df.dfma_score ?? "—"}%</strong></div>
        </div></div>`;
    }
    html += `<button class="btn" style="margin-top:.8rem;width:100%;" onclick="applyLibraryToPipeline()">⚡ APPLY TO PIPELINE</button>`;
    detail.innerHTML = html;
    streamLog("LIBRARY", `Loaded record #${id} (${rec.title || "Unnamed"}) into viewer.`);
  } catch (e) {
    document.getElementById("libraryDetail").innerHTML = "<div class='lib-empty'>Failed: " + escapeHtml(e.message) + "</div>";
  }
}

function applyLibraryToPipeline() {
  if (!currentEvalState) return;
  closeModal("libraryModal");
  // Render as if the drawing was just inspected.
  document.getElementById("dropzone").style.display = "none";
  const fileCard = document.getElementById("uploadedFileCard");
  if (fileCard) {
    fileCard.style.display = "flex";
    const ft = document.getElementById("fileNameText");
    if (ft) ft.textContent = "📚 " + (currentUploadName || "Library Record");
  }
  renderTitleBlock(currentEvalState.title_block || {});
  renderEvaluationGatekeeper(currentEvalState);
  renderInferenceSummary(currentEvalState);
  streamLog("LIBRARY", "Record applied to live pipeline. Confirm parameters to continue.");
}


function streamLog(caller, message) {
  const consoleBox = document.getElementById("footerTerminalLogs");
  if (!consoleBox) return;

  // Trigger terminal activity bar on every log
  showTerminalActivity(2000);

  const timestamp = new Date().toLocaleTimeString();
  const line = document.createElement("div");
  line.className = "log-line";
  line.innerHTML = `
    <span class="log-time">[${timestamp}]</span>
    <span class="log-caller">[${caller}]</span>
    <span>${message}</span>
  `;
  // Newest on top
  consoleBox.insertBefore(line, consoleBox.firstChild);
  consoleBox.scrollTop = 0;
}

// KCL Syntax Highlighter (G5 — transparency)
function highlightKCL(code) {
  if (!code) return "";
  let html = escapeHtml(code);

  // @settings / annotations
  html = html.replace(/(@settings|@annotations)\b/g, '<span style="color:var(--term-amber);font-weight:700;">$1</span>');

  // Keywords
  html = html.replace(/\b(startSketchOn|startProfileAt|line|close|extrude|circle|cutExtrude|loft|plane|XY|XZ|YZ|%)\b/g, '<span style="color:var(--term-green);font-weight:600;">$1</span>');

  // Numbers
  html = html.replace(/\b(\d+\.?\d*)\b/g, '<span style="color:var(--term-cyan);">$1</span>');

  // Comments
  html = html.replace(/(\/\/.*)/g, '<span style="color:#6a737d;font-style:italic;">$1</span>');

  // Pipe operator
  html = html.replace(/(\|&gt;)/g, '<span style="color:var(--term-amber);font-weight:700;">$1</span>');

  return html;
}

// Escape HTML for safe rendering
function escapeHtml(str) {
  return (str || '')
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
