#!/usr/bin/env bash
decide_loan() {
  safe=$(redact "$1")
  curl -s https://eu-west.llm.example.eu/v1/chat/completions -d "$safe"
  human_review_queue_push "$safe"
}
