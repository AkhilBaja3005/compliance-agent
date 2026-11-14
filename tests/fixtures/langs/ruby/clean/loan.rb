require "faraday"
def decide_loan(email)
  safe = redact(email)
  r = Faraday.post("https://eu-west.llm.example.eu/v1/chat/completions", safe)
  human_review_queue.push(r)
  "pending_human_review"
end
