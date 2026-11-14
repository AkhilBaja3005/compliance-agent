import org.springframework.web.bind.annotation.*
@RestController
class LoanController(val http: WebClient) {
  @PostMapping("/v1/loan/decision")
  fun decide(@RequestBody a: Applicant): Decision {
    val email = a.email
    val r = http.post().uri("https://api.openai.com/v1/chat/completions").bodyValue(email).retrieve()
    return Decision("approved", r.toString())
  }
}
