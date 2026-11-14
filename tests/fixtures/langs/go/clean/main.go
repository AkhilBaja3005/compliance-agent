package main
import ("net/http"; "bytes")
func decideLoan(w http.ResponseWriter, r *http.Request) {
  email := redact(r.FormValue("email"))
  resp, _ := http.Post("https://eu-west.llm.example.eu/v1/chat/completions", "application/json", bytes.NewBufferString(email))
  _ = resp
  human_review_queue.Add(email)
  w.Write([]byte("pending_human_review"))
}
func main() { http.HandleFunc("/v1/loan/decision", decideLoan); http.ListenAndServe(":8080", nil) }
