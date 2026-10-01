variable "repository_prefix" {
  description = "Repositories are named <prefix>/<service>. Must match the prefix the deploy role is scoped to."
  type        = string
  default     = "retail"
}

variable "services" {
  description = "One repository per image: the four service images and the UI."
  type        = set(string)
  default     = ["product", "inventory", "order", "notification", "ui"]
}

variable "keep_images" {
  description = "Lifecycle: keep this many most recent images per repository."
  type        = number
  default     = 30
}
