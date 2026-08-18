output "cloudfront_domain_name" {
  description = "Public URL host (default *.cloudfront.net or your alias)"
  value       = aws_cloudfront_distribution.anra.domain_name
}

output "cloudfront_id" {
  value = aws_cloudfront_distribution.anra.id
}

output "cloudfront_arn" {
  value = aws_cloudfront_distribution.anra.arn
}
