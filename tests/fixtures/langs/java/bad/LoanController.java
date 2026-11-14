import org.springframework.web.bind.annotation.*;
@RestController
public class LoanController {
  private final RestTemplate http = new RestTemplate();
  @PostMapping("/v1/loan/decision")
  public Decision decide(@RequestBody Applicant a) {
    String email = a.getEmail();
    String r = http.postForObject("https://api.openai.com/v1/chat/completions", email, String.class);
    return new Decision("approved", r);
  }
}
