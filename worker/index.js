// StonksTeller scheduler: a Cloudflare Worker whose only job is to start the
// GitHub Actions workflows on time, because GitHub's own cron does not.
//
// Secrets / variables (Worker settings > Variables and Secrets):
//   GITHUB_TOKEN  secret   fine-grained token for the repo, "Actions: Read and write" only
//   GITHUB_REPO   text     e.g. "GabrielYamin/StonksTeller"
//
// Cron triggers (Worker settings > Triggers), all UTC:
//   35 13-21 * * 1-5   hourly during US market hours, summer and winter  -> post.yml
//   any other trigger  (for example */5 * * * *)                         -> commands.yml
// The Python script still checks the NYSE calendar, so a dispatch while the
// market is closed just exits.

const POST_CRON = "35 13-21 * * 1-5";

export default {
  async scheduled(event, env, ctx) {
    const workflow = event.cron === POST_CRON ? "post.yml" : "commands.yml";
    ctx.waitUntil(dispatch(env, workflow));
  },

  // Visiting the Worker's URL only reports that it is alive; it never dispatches.
  async fetch() {
    return new Response("StonksTeller scheduler is running. Dispatches happen on the cron triggers.\n", {
      headers: { "content-type": "text/plain" },
    });
  },
};

async function dispatch(env, workflow) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${workflow}/dispatches`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "StonksTeller-scheduler",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  if (response.status === 204) {
    console.log(`dispatched ${workflow}`);
  } else {
    console.error(`GitHub returned ${response.status} for ${workflow}: ${(await response.text()).slice(0, 300)}`);
  }
}
