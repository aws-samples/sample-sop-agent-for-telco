variable "aws_region" {
  type        = string
  description = "Region where Terraform runs (e.g. us-east-1). Not the CloudFront edge region."
  default     = "us-east-1"
}

variable "alb_dns_name" {
  type        = string
  description = "ALB hostname from: kubectl get ingress anra -n anra (status.loadBalancer.ingress[0].hostname), no protocol."
}

variable "comment" {
  type        = string
  default     = "ANRA dashboard (dynamic — caching disabled)"
}

variable "price_class" {
  type        = string
  default     = "PriceClass_100"
  description = "Use PriceClass_200/All for global edges if required."
}

variable "cloudfront_alias" {
  type        = list(string)
  default     = []
  description = "Optional custom domain names. When non-empty, set acm_certificate_arn_us_east_1 (ACM in us-east-1)."
}

variable "acm_certificate_arn_us_east_1" {
  type        = string
  default     = null
  description = "If using cloudfront_alias, ACM cert for those names in us-east-1 (CloudFront requirement)."
}

variable "alb_origin_protocol" {
  type        = string
  default     = "http-only"
  description = "Match the ALB: use http-only if the ALB only listens on 80; use https-only when the ALB terminates TLS on 443."
}
