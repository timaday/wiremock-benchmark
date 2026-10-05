import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import com.fasterxml.jackson.core.type.TypeReference;
import io.pockethive.work.config.WorkConfigurationMode;
import io.pockethive.work.config.composition.CurrentWorkConfigurationProviders;
import java.nio.file.*;
import java.util.Map;
class WorkConfigProbe {
 public static void main(String[] args) throws Exception {
  var mapper=new ObjectMapper(new YAMLFactory()).findAndRegisterModules();
  var parser=new CurrentWorkConfigurationProviders().workConfigurationParser();
  int count=0;
  for(String file:args){
   var root=mapper.readTree(Files.readString(Path.of(file)));
   for(var bee:root.get("template").get("bees")){
    Map<String,Object> config=mapper.convertValue(bee.get("config"),new TypeReference<>(){});
    var result=parser.validate(config,WorkConfigurationMode.AUTHORING);
    if(!result.problems().isEmpty())throw new AssertionError(bee.get("role")+": "+result.problems());
    count++;
   }
  }
  System.out.println("PASS: deployed-release Work configuration parser accepted "+count+" worker declarations.");
 }
}
