import property_parser

# Example 1: Create a list of properties from data file.
def ex1():
    fileName = 'property_parser_tester_item.txt'
    fileContents = []
    with open(fileName) as f:
        for line in f:
            fileContents.append(f)
    properties = Property.parse(fileContents)
    return properties
  
# Example 2: Write property data back to a file
def ex2(properties):
    propertiesOutput = []
    for p in properties:
        for s in p.to_strings():
            propertiesOutput.append(s)
    with open('property_parser_tester_output.txt', 'w') as f:
        f.writelines(line + '\n' for line in propertiesOutput)

# Call examples
properties = ex1()
ex2(properties)