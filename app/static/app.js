const form = document.getElementById("sim-form");
const submitBtn = document.getElementById("submit-btn");
const statusSection = document.getElementById("status");
const statusText = document.getElementById("status-text");
const reportLink = document.getElementById("report-link");

const POLL_INTERVAL_MS = 2000;

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  submitBtn.disabled = true;
  statusSection.hidden = false;
  reportLink.hidden = true;
  statusText.textContent = "Submitting...";

  const body = {
    profile: document.getElementById("profile").value,
    iterations: Number(document.getElementById("iterations").value),
    fight_style: document.getElementById("fight_style").value,
  };

  try {
    const response = await fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error(`server returned ${response.status}`);
    }
    const job = await response.json();
    pollJob(job.job_id);
  } catch (err) {
    statusText.textContent = `Failed to submit: ${err.message}`;
    submitBtn.disabled = false;
  }
});

async function pollJob(jobId) {
  statusText.textContent = "Queued...";

  const poll = async () => {
    const response = await fetch(`/api/simulate/${jobId}`);
    const job = await response.json();

    if (job.status === "queued" || job.status === "running") {
      statusText.textContent = `Status: ${job.status}`;
      setTimeout(poll, POLL_INTERVAL_MS);
      return;
    }

    submitBtn.disabled = false;

    if (job.status === "done") {
      statusText.textContent = "Done!";
      reportLink.href = job.report_url;
      reportLink.hidden = false;
    } else {
      statusText.textContent = `Simulation failed: ${job.error ?? "unknown error"}`;
    }
  };

  poll();
}
