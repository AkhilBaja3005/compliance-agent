#!/usr/bin/env bash
decide_loan() {
  curl -s https://api.openai.com/v1/chat/completions -d "$1"
}
