import org.springframework.web.bind.annotation.*
@RestController
class LoanController(val http: WebClient) {
  @PostMapping("/v1/loan/decision")
  fun decide(@RequestBody a: Applicant): Decision {
    val email = redact(a.email)
    val r = http.post().uri("https://eu-west.llm.example.eu/v1/chat/completions").bodyValue(email).retrieve()
    humanReviewQueue.add(r)
    return Decision("pending_human_review", r.toString())
  }
}
