# CloudFront in front of the EKS ALB created by AWS Load Balancer Controller.
# Caching is disabled (dashboard + /api are dynamic).

data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewer"
}

resource "aws_cloudfront_distribution" "anra" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = var.comment
  price_class     = var.price_class
  aliases         = var.cloudfront_alias

  origin {
    origin_id   = "anra-alb"
    domain_name = var.alb_dns_name

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = var.alb_origin_protocol
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60
    }
  }

  default_cache_behavior {
    target_origin_id       = "anra-alb"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    allowed_methods = [
      "DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"
    ]
    cached_methods = ["GET", "HEAD"]

    cache_policy_id          = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = length(var.cloudfront_alias) == 0
    acm_certificate_arn            = length(var.cloudfront_alias) > 0 ? var.acm_certificate_arn_us_east_1 : null
    ssl_support_method             = length(var.cloudfront_alias) > 0 ? "sni-only" : null
    minimum_protocol_version       = length(var.cloudfront_alias) > 0 ? "TLSv1.2_2021" : null
  }
}
