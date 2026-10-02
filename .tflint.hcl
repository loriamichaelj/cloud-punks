# tflint for infra/terraform. Run by pr.yml with --recursive from that directory.
config {
  call_module_type = "none"   # the modules are linted on their own by --recursive
}

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "aws" {
  enabled = true
  version = "0.49.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}
