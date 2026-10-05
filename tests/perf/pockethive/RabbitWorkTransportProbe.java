import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import io.pockethive.artemis.api.ArtemisConnectionSettings;
import io.pockethive.artemis.work.ArtemisWorkBootstrapEnvironment;
import io.pockethive.rabbit.api.RabbitConnectionSettings;
import io.pockethive.rabbit.api.RabbitWorkSettingsBootstrap;
import io.pockethive.rabbit.work.RabbitWorkBootstrapEnvironment;
import io.pockethive.work.config.WorkConfigurationMode;
import io.pockethive.work.config.composition.CurrentWorkConfigurationProviders;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

/** Checks Rabbit bundle bootstrap and rejection with the wrong deployment adapter; opens no connections. */
class RabbitWorkTransportProbe {
    public static void main(String[] args) throws Exception {
        var mapper = new ObjectMapper(new YAMLFactory()).findAndRegisterModules();
        var parser = new CurrentWorkConfigurationProviders().workConfigurationParser();
        var rabbit = new RabbitWorkBootstrapEnvironment(
            new RabbitConnectionSettings("probe.invalid", 5672, "probe", "probe", "/"));
        var artemis = new ArtemisWorkBootstrapEnvironment(
            new ArtemisConnectionSettings("tcp://probe.invalid:61616", "probe", "probe", 30000));
        var destinations = Map.of(
            RabbitWorkSettingsBootstrap.INPUT_QUEUE_ENV, "probe.queue",
            RabbitWorkSettingsBootstrap.OUTPUT_EXCHANGE_ENV, "probe.exchange",
            RabbitWorkSettingsBootstrap.OUTPUT_ROUTING_KEY_ENV, "probe.route");
        int count = 0;
        for (String file : args) {
            var scenario = mapper.readTree(Files.readString(Path.of(file)));
            for (var bee : scenario.get("template").get("bees")) {
                Map<String, Object> config = mapper.convertValue(bee.get("config"), new TypeReference<>() {});
                var correct = parser.validate(rabbit.bootstrap(config, destinations).configuration(),
                    WorkConfigurationMode.RESOLVED);
                if (!correct.problems().isEmpty()) {
                    throw new AssertionError(bee.get("role") + ": " + correct.problems());
                }
                var wrong = parser.validate(artemis.bootstrap(config, Map.of()).configuration(),
                    WorkConfigurationMode.RESOLVED);
                if (wrong.problems().stream().noneMatch(problem -> problem.path().contains(".rabbit."))) {
                    throw new AssertionError("Expected unresolved Rabbit destination: " + bee.get("role"));
                }
                count++;
            }
        }
        if (count == 0) throw new AssertionError("No worker declarations checked");
        System.out.println("PASS: " + count + " workers resolve with RabbitMQ and fail resolved validation with Artemis.");
    }
}
