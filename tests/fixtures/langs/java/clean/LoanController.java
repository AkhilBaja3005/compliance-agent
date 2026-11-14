import org.springframework.web.bind.annotation.*;
@RestController
public class LoanController {
  private final RestTemplate http = new RestTemplate();
  @PostMapping("/v1/loan/decision")
  public Decision decide(@RequestBody Applicant a) {
    String email = redact(a.getEmail());
    String r = http.postForObject("https://eu-west.llm.example.eu/v1/chat/completions", email, String.class);
    humanReviewQueue.add(r);  // human_review_queue gate
    return new Decision("pending_human_review", r);
  }
}
