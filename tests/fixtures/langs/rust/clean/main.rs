async fn decide_loan(email: String) -> String {
    let safe = redact(&email);
    let client = reqwest::Client::new();
    let r = client.post("https://eu-west.llm.example.eu/v1/chat/completions").body(safe).send().await;
    human_review_queue.push(r);
    "pending_human_review".to_string()
}
