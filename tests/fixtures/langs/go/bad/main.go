package main
import ("net/http"; "bytes")
func decideLoan(w http.ResponseWriter, r *http.Request) {
  email := r.FormValue("email")
  resp, _ := http.Post("https://api.openai.com/v1/chat/completions", "application/json", bytes.NewBufferString(email))
  _ = resp
  w.Write([]byte("approved"))
}
func main() { http.HandleFunc("/v1/loan/decision", decideLoan); http.ListenAndServe(":8080", nil) }
