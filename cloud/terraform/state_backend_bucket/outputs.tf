output "bucket_name" {
  description = "Dedicated private bucket name for the later state migration."
  value       = google_storage_bucket.terraform_state.name
}
