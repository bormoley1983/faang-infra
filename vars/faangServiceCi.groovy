def call(Map configuration = [:]) {
    List<String> integrationTasks = (configuration.integrationTasks ?: []) as List<String>
    List<String> verificationTasks = ['clean', 'build'] + integrationTasks
    String taskArguments = verificationTasks.collect { String task ->
        if (!(task ==~ /[A-Za-z][A-Za-z0-9_-]*/)) {
            error("Invalid Gradle task name: ${task}")
        }
        task
    }.join(' ')

    podTemplate(yaml: '''
apiVersion: v1
kind: Pod
spec:
  serviceAccountName: faang-build-agent
  automountServiceAccountToken: false
  nodeSelector:
    workload.faang.io/ci-heavy: "true"
    kubernetes.io/arch: amd64
  securityContext:
    fsGroup: 1000
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: jdk
      image: eclipse-temurin:25-jdk-alpine@sha256:09349d79941fd53bb3d487b393ca118d8853c08c09193f416fe6a8718df9e732
      imagePullPolicy: IfNotPresent
      command: ["sleep"]
      args: ["3600"]
      workingDir: /home/jenkins/agent
      env:
        - name: GRADLE_USER_HOME
          value: /home/jenkins/agent/.gradle
      resources:
        requests:
          cpu: 250m
          memory: 768Mi
        limits:
          cpu: "2"
          memory: 3Gi
      securityContext:
        allowPrivilegeEscalation: false
        runAsUser: 1000
        runAsGroup: 1000
        capabilities:
          drop: ["ALL"]
      volumeMounts:
        - name: untrusted-gradle-cache
          mountPath: /home/jenkins/agent/.gradle
  volumes:
    - name: untrusted-gradle-cache
      emptyDir:
        sizeLimit: 2Gi
''') {
        node(POD_LABEL) {
            timeout(time: 30, unit: 'MINUTES') {
                stage('Checkout') {
                    deleteDir()
                    checkout scm
                }

                stage('Validate wrapper') {
                    container('jdk') {
                        sh '''
                            test -x ./gradlew
                            test -f gradle/wrapper/gradle-wrapper.jar
                            test -f gradle/wrapper/gradle-wrapper.properties
                            ./gradlew --version --no-daemon
                        '''
                    }
                }

                stage('Compile, test, coverage, and integration') {
                    container('jdk') {
                        try {
                            sh "./gradlew ${taskArguments} --no-daemon --stacktrace"
                        } finally {
                            archiveArtifacts(
                                artifacts: 'build/test-results/**/*.xml,build/reports/**',
                                allowEmptyArchive: true,
                                fingerprint: true
                            )
                        }
                    }
                }
            }
        }
    }
}
