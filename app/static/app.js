const form = document.getElementById("sim-form");
const submitBtn = document.getElementById("submit-btn");
const cancelBtn = document.getElementById("cancel-btn");
const statusSection = document.getElementById("status");
const statusText = document.getElementById("status-text");
const profileInput = document.getElementById("profile");
const candidatesSection = document.getElementById("candidates");
const candidateList = document.getElementById("candidate-list");
const droptimizerToggles = document.getElementById("droptimizer-toggles");
const droptimizerPreview = document.getElementById("droptimizer-preview");
const droptimizerCategories = document.getElementById("droptimizer-categories");

const POLL_INTERVAL_MS = 1000;

const SUBMIT_LABELS = {
  quick: "Run simulation",
  topgear: "Find gear",
  droptimizer: "Preview drops",
};

let mode = "quick"; // "quick" | "topgear" | "droptimizer"
let currentJobId = null;
let previewLoaded = false;

const tabs = {
  quick: document.getElementById("tab-quick"),
  topgear: document.getElementById("tab-topgear"),
  droptimizer: document.getElementById("tab-droptimizer"),
};
const hints = {
  quick: document.getElementById("hint-quick"),
  topgear: document.getElementById("hint-topgear"),
  droptimizer: document.getElementById("hint-droptimizer"),
};

function setMode(next) {
  mode = next;
  for (const key of Object.keys(tabs)) {
    tabs[key].classList.toggle("active", key === mode);
    hints[key].hidden = key !== mode;
  }
  candidatesSection.hidden = true;
  droptimizerPreview.hidden = true;
  droptimizerToggles.hidden = mode !== "droptimizer";
  previewLoaded = false;
  submitBtn.textContent = SUBMIT_LABELS[mode];
}

tabs.quick.addEventListener("click", () => setMode("quick"));
tabs.topgear.addEventListener("click", () => setMode("topgear"));
tabs.droptimizer.addEventListener("click", () => setMode("droptimizer"));

// Re-parse if the profile changes after a preview was shown.
profileInput.addEventListener("input", () => {
  if (mode !== "quick" && previewLoaded) {
    previewLoaded = false;
    candidatesSection.hidden = true;
    droptimizerPreview.hidden = true;
    submitBtn.textContent = SUBMIT_LABELS[mode];
  }
});

function simOptions() {
  return {
    profile: profileInput.value,
    iterations: Number(document.getElementById("iterations").value),
    fight_style: document.getElementById("fight_style").value,
    desired_targets: Number(document.getElementById("desired_targets").value),
    max_time: Number(document.getElementById("max_time").value),
    bloodlust: document.getElementById("bloodlust").checked,
    raid_buffs: document.getElementById("raid_buffs").checked,
    consumables: document.getElementById("consumables").checked,
  };
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `server returned ${response.status}`;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return response.json();
}

function renderCandidates(candidates) {
  candidateList.innerHTML = "";
  for (const candidate of candidates) {
    const label = document.createElement("label");
    label.className = "candidate";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.dataset.index = candidate.index;

    const text = document.createElement("span");
    const ilvl = candidate.ilevel ? ` (${candidate.ilevel})` : "";
    text.textContent = `${candidate.name}${ilvl} — ${candidate.slot}`;

    const source = document.createElement("span");
    source.className = `source-tag ${candidate.source}`;
    source.textContent = candidate.source;

    label.append(checkbox, text, source);
    candidateList.append(label);
  }
  candidatesSection.hidden = false;
}

function selectedIndices() {
  return [...candidateList.querySelectorAll("input:checked")].map((cb) =>
    Number(cb.dataset.index)
  );
}

function renderCategories(byCategory) {
  droptimizerCategories.innerHTML = "";
  for (const entry of byCategory) {
    const label = document.createElement("label");
    label.className = "candidate";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.dataset.category = entry.category;

    const text = document.createElement("span");
    text.textContent = `${entry.category.replace("_", " ")} (${entry.count})`;

    label.append(checkbox, text);
    droptimizerCategories.append(label);
  }
  droptimizerPreview.hidden = false;
}

function selectedCategories() {
  return [...droptimizerCategories.querySelectorAll("input:checked")].map(
    (cb) => cb.dataset.category
  );
}

async function handleDroptimizerSubmit() {
  if (!previewLoaded) {
    statusSection.hidden = false;
    statusText.textContent = "Loading catalog...";
    try {
      const preview = await postJson("/api/droptimizer/preview", {
        profile: profileInput.value,
      });
      if (preview.total_sources === 0) {
        statusText.textContent =
          "No droptimizer items matched this character in the catalog.";
        return;
      }
      renderCategories(preview.by_category);
      previewLoaded = true;
      submitBtn.textContent = "Run Droptimizer";
      const classNote = preview.wow_class ? ` (${preview.wow_class})` : "";
      statusText.textContent =
        `${preview.season} — ${preview.total_sources} drop source(s)${classNote}. ` +
        "Untick any category you don't want, then run.";
    } catch (err) {
      statusText.textContent = `Failed to load catalog: ${err.message}`;
    }
    return;
  }

  const categories = selectedCategories();
  if (categories.length === 0) {
    statusText.textContent = "Select at least one source category.";
    return;
  }
  await submitJob("/api/droptimizer", {
    ...simOptions(),
    use_max_upgrade: document.getElementById("use_max_upgrade").checked,
    voidcore: document.getElementById("voidcore").checked,
    categories,
  });
}

async function handleTopGearSubmit() {
  if (!previewLoaded) {
    statusSection.hidden = false;
    statusText.textContent = "Parsing export...";
    try {
      const preview = await postJson("/api/topgear/preview", {
        profile: profileInput.value,
      });
      if (preview.candidates.length === 0) {
        statusText.textContent =
          "No bag or vault items found in this export. Make sure you paste the full /simc addon output.";
        return;
      }
      renderCandidates(preview.candidates);
      previewLoaded = true;
      submitBtn.textContent = "Run Top Gear";
      statusText.textContent = `Found ${preview.candidates.length} item(s). Untick anything you don't care about, then run.`;
    } catch (err) {
      statusText.textContent = `Failed to parse: ${err.message}`;
    }
    return;
  }

  const selected = selectedIndices();
  if (selected.length === 0) {
    statusText.textContent = "Select at least one item to compare.";
    return;
  }
  await submitJob("/api/topgear", { ...simOptions(), selected });
}

async function submitJob(url, body) {
  submitBtn.disabled = true;
  statusSection.hidden = false;
  statusText.textContent = "Submitting...";

  try {
    const job = await postJson(url, body);
    currentJobId = job.job_id;
    cancelBtn.hidden = false;
    pollJob(job.job_id);
  } catch (err) {
    statusText.textContent = `Failed to submit: ${err.message}`;
    submitBtn.disabled = false;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (mode === "topgear") {
    await handleTopGearSubmit();
  } else if (mode === "droptimizer") {
    await handleDroptimizerSubmit();
  } else {
    await submitJob("/api/simulate", simOptions());
  }
});

cancelBtn.addEventListener("click", async () => {
  if (!currentJobId) return;
  cancelBtn.disabled = true;
  await fetch(`/api/simulate/${currentJobId}/cancel`, { method: "POST" });
});

function finishPolling() {
  submitBtn.disabled = false;
  cancelBtn.hidden = true;
  cancelBtn.disabled = false;
  currentJobId = null;
}

function runningLabel(job) {
  const parts = [`Status: ${job.status}`];
  if (job.progress != null) {
    parts.push(`${job.progress.toFixed(0)}%`);
  }
  if (job.elapsed != null) {
    parts.push(`${job.elapsed.toFixed(0)}s elapsed`);
  }
  return parts.join(" — ");
}

async function pollJob(jobId) {
  statusText.textContent = "Queued...";

  const poll = async () => {
    const response = await fetch(`/api/simulate/${jobId}`);
    const job = await response.json();

    if (job.status === "queued" || job.status === "running") {
      statusText.textContent = runningLabel(job);
      setTimeout(poll, POLL_INTERVAL_MS);
      return;
    }

    finishPolling();

    if (job.status === "done") {
      statusText.textContent = "Done! Redirecting to report...";
      window.location.href = job.summary_url;
    } else if (job.status === "cancelled") {
      statusText.textContent = "Simulation cancelled.";
    } else {
      statusText.textContent = `Simulation failed: ${job.error ?? "unknown error"}`;
    }
  };

  poll();
}
