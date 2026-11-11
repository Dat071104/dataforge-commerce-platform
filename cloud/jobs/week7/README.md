# Week-7 dbt Cloud Run Job image

The image contains only the pinned dbt BigQuery project and its profile template. The template has environment references only; it contains no key, token, or account credential. Cloud Run supplies Application Default Credentials through the attached keyless service account.

Build from the repository root so the context includes `dbt/dataforge/`:

```powershell
docker build --file cloud/jobs/week7/Dockerfile --tag dataforge-week7-dbt:local .
docker run --rm dataforge-week7-dbt:local --version
docker run --rm dataforge-week7-dbt:local --target offline parse
```

The deployed reference is `us-central1-docker.pkg.dev/dataforge-p7-lab-d0f725/dataforge-week7/dbt@sha256:<digest>`. Build and push steps belong to the authorized Week-7 release workflow; never put a service-account key or short-lived token in the image or build context. Terraform pins the deployed image by digest and keeps the Cloud Run Job finite, single-task, low-resource, and bounded by a short timeout.

The root `.dockerignore` excludes local credentials, Terraform state, raw/generated data, and dbt artifacts from the Docker build context.
