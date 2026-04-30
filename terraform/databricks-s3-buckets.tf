# S3 buckets for Databricks: shared DBFS root and Unity Catalog managed storage.
# After apply, grant your Databricks workspace IAM role (instance profile or cross-account role)
# read/write on these buckets via bucket policy or IAM policy as required by your deployment model.

terraform {
  required_version = ">= 1.3"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  type        = string
  description = "AWS region for the buckets."
  default     = "us-east-1"
}

variable "resource_prefix" {
  type        = string
  description = "Short prefix for bucket names; combined with a random suffix for global uniqueness."
  nullable    = false
}

variable "tags" {
  type        = map(string)
  description = "Extra tags merged onto both buckets."
  default     = {}
}

resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  dbfs_bucket_name = lower("${var.resource_prefix}-dbfs-root-${random_id.suffix.hex}")
  uc_bucket_name   = lower("${var.resource_prefix}-unity-catalog-${random_id.suffix.hex}")
}

# ---------------------------------------------------------------------------
# DBFS root (workspace shared root storage)
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "dbfs_root" {
  bucket = local.dbfs_bucket_name

  tags = merge(
    var.tags,
    {
      Name    = "Databricks DBFS root"
      Purpose = "databricks-dbfs-root"
    },
  )
}

resource "aws_s3_bucket_public_access_block" "dbfs_root" {
  bucket = aws_s3_bucket.dbfs_root.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "dbfs_root" {
  bucket = aws_s3_bucket.dbfs_root.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = false
  }
}

resource "aws_s3_bucket_versioning" "dbfs_root" {
  bucket = aws_s3_bucket.dbfs_root.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "dbfs_root" {
  bucket = aws_s3_bucket.dbfs_root.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }

    filter {}
  }
}

# ---------------------------------------------------------------------------
# Unity Catalog managed storage
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "unity_catalog" {
  bucket = local.uc_bucket_name

  tags = merge(
    var.tags,
    {
      Name    = "Databricks Unity Catalog storage"
      Purpose = "databricks-unity-catalog"
    },
  )
}

resource "aws_s3_bucket_public_access_block" "unity_catalog" {
  bucket = aws_s3_bucket.unity_catalog.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "unity_catalog" {
  bucket = aws_s3_bucket.unity_catalog.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = false
  }
}

resource "aws_s3_bucket_versioning" "unity_catalog" {
  bucket = aws_s3_bucket.unity_catalog.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "unity_catalog" {
  bucket = aws_s3_bucket.unity_catalog.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }

    filter {}

    # UC workloads can generate many small objects; tune transitions if you use lifecycle tiers.
  }
}

# ---------------------------------------------------------------------------
# Outputs (for workspace / metastore configuration and IAM policies)
# ---------------------------------------------------------------------------

output "dbfs_root_bucket_id" {
  description = "S3 bucket name for DBFS root."
  value       = aws_s3_bucket.dbfs_root.id
}

output "dbfs_root_bucket_arn" {
  description = "S3 bucket ARN for DBFS root (use in IAM/bucket policies)."
  value       = aws_s3_bucket.dbfs_root.arn
}

output "unity_catalog_bucket_id" {
  description = "S3 bucket name for Unity Catalog managed storage / external locations."
  value       = aws_s3_bucket.unity_catalog.id
}

output "unity_catalog_bucket_arn" {
  description = "S3 bucket ARN for Unity Catalog (use in storage credentials and IAM policies)."
  value       = aws_s3_bucket.unity_catalog.arn
}
