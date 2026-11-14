async fn decide_loan(email: String) -> String {
    let client = reqwest::Client::new();
    let _r = client.post("https://api.openai.com/v1/chat/completions").body(email).send().await;
    "approved".to_string()
}
